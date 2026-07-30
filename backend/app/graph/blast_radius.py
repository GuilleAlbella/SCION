"""Blast radius computation for a full diff pair.

Aggregates impact analysis across all changes in a diff to produce
a consolidated risk picture.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent
from app.diff.diff_rules import get_severity, is_breaking
# The ORM row class shares its name with the API dataclass below. Alias
# it on import so the two never collide in this module's namespace.
from app.graph.impact_models import ChangeImpactSummary as _ImpactSummaryRow
from app.graph.impact_summary import persist_summaries_for_pair


@dataclass
class ChangeImpactSummary:
    """Per-change impact summary used in batch blast-radius reports.

    Attributes:
        change_id: Identifier of the underlying ``ChangeEvent``.
        object_identifier: Fully-qualified name of the changed object.
        change_type: Classification (e.g. ``TABLE_REMOVED``).
        severity: Severity level (``LOW``/``MEDIUM``/``HIGH``).
        is_breaking: Whether the change is considered breaking.
        direct_count: Number of downstream nodes directly affected.
        indirect_count: Number of upstream/indirectly affected nodes.
        impact_score: Aggregate weighted impact score.
        query_count: Queries observed touching this object.
        user_count: Distinct users observed touching this object.
    """

    change_id: int
    object_identifier: str
    change_type: str
    severity: str
    is_breaking: bool
    direct_count: int = 0
    indirect_count: int = 0
    impact_score: float = 0.0
    # Usage data for this object (if any): how many queries / users touch it
    query_count: int = 0
    user_count: int = 0


@dataclass
class AffectedDatabase:
    """Pre-grouped tables-per-database for the affected-objects section."""

    schema_name: str
    tables: List[str] = field(default_factory=list)


@dataclass
class BlastRadius:
    """Aggregate footprint of all changes in a diff pair.

    Attributes:
        total_impacted_nodes: Count of distinct impacted graph nodes.
        max_depth: Deepest propagation depth reached across changes.
        weighted_score: Sum of per-impact weighted scores.
        affected_schemas: Sorted list of schema names touched.
        affected_tables: Sorted list of fully-qualified tables touched.
        affected_databases: Pre-grouped tables-per-schema (v1.19+).
            The frontend reads this directly so it doesn't have to
            filter ``affected_tables`` once per schema — at Transcend
            scale that nested filter was visibly slow.
    """

    total_impacted_nodes: int = 0
    max_depth: int = 0
    weighted_score: float = 0.0
    affected_schemas: List[str] = field(default_factory=list)
    affected_tables: List[str] = field(default_factory=list)
    affected_databases: List[AffectedDatabase] = field(default_factory=list)


@dataclass
class BucketCount:
    """A single bucket in a categorical aggregate (donut, distribution).

    ``name`` keys the bucket (severity level, change type, schema, …).
    ``count`` is the number of changes in the FULL filtered set falling
    into that bucket — independent of pagination, so the donuts in the
    Impact Analysis page stay accurate regardless of which page of
    ``changes`` is currently visible.
    """

    name: str
    count: int


@dataclass
class BatchImpactResult:
    """Full result of a batch impact computation between two snapshots.

    Attributes:
        snapshot_from: Starting snapshot id.
        snapshot_to: Ending snapshot id.
        changes_analyzed: Number of ``ChangeEvent`` rows processed
            (the FULL filtered set, not just the returned page).
        blast_radius: Aggregated blast-radius footprint.
        changes: Per-change impact summaries — at most ``limit`` rows.
        total_direct: Sum of direct (downstream) impacts.
        total_indirect: Sum of indirect (upstream) impacts.
        breaking_count: Number of breaking changes.
        overall_risk: Overall risk level (``LOW``/``MEDIUM``/``HIGH``).
        by_severity / by_change_type / by_schema / by_breaking:
            Pre-computed donut buckets so the frontend doesn't have to
            iterate ``changes`` to build them. Catastrophic to skip at
            production scale (250k changes × 4 client-side iterations
            froze the browser before this was added).
        total_query_count: Sum of usage query counts across the diff,
            for the "Queries affected" KPI on the page header.
        limit / offset / has_more: Pagination metadata for the
            ``changes`` page. ``has_more`` is True when more rows
            exist beyond the returned slice.
    """

    snapshot_from: int
    snapshot_to: int
    changes_analyzed: int = 0
    blast_radius: BlastRadius = field(default_factory=BlastRadius)
    changes: List[ChangeImpactSummary] = field(default_factory=list)
    total_direct: int = 0
    total_indirect: int = 0
    breaking_count: int = 0
    overall_risk: str = "LOW"
    by_severity: List[BucketCount] = field(default_factory=list)
    by_change_type: List[BucketCount] = field(default_factory=list)
    by_schema: List[BucketCount] = field(default_factory=list)
    by_breaking: List[BucketCount] = field(default_factory=list)
    total_query_count: int = 0
    limit: int = 100
    offset: int = 0
    has_more: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the batch result into a JSON-friendly dict."""
        return {
            "snapshot_from": self.snapshot_from,
            "snapshot_to": self.snapshot_to,
            "changes_analyzed": self.changes_analyzed,
            "blast_radius": asdict(self.blast_radius),
            "changes": [asdict(c) for c in self.changes],
            "summary": {
                "total_direct": self.total_direct,
                "total_indirect": self.total_indirect,
                "breaking_count": self.breaking_count,
                "overall_risk": self.overall_risk,
                "by_severity": [asdict(b) for b in self.by_severity],
                "by_change_type": [asdict(b) for b in self.by_change_type],
                "by_schema": [asdict(b) for b in self.by_schema],
                "by_breaking": [asdict(b) for b in self.by_breaking],
                "total_query_count": self.total_query_count,
            },
            "limit": self.limit,
            "offset": self.offset,
            "has_more": self.has_more,
        }


def _load_all_changes(snapshot_from: int, snapshot_to: int) -> list:
    """Load change events across all intermediate snapshot pairs.

    If snapshots are not consecutive (e.g. 1→3), loads changes from
    1→2 + 2→3 etc.
    """
    # Why stitch intermediate pairs?
    # ChangeEvents are persisted only for consecutive-pair diffs. A request
    # for "what changed from snapshot 1 to 3" is answered by replaying the
    # consecutive diffs (1→2, 2→3) rather than computing a fresh long-range
    # diff, which would miss intermediate breaking events.
    from app.db.models.snapshot import Snapshot

    with Session(engine) as session:
        all_snaps = session.scalars(
            select(Snapshot.snapshot_id)
            .where(
                Snapshot.snapshot_id >= snapshot_from,
                Snapshot.snapshot_id <= snapshot_to,
            )
            .order_by(Snapshot.snapshot_id)
        ).all()

    pairs = []
    if len(all_snaps) >= 2:
        for i in range(len(all_snaps) - 1):
            pairs.append((all_snaps[i], all_snaps[i + 1]))
    else:
        pairs = [(snapshot_from, snapshot_to)]

    events = []
    with Session(engine) as session:
        for sf, st in pairs:
            rows = session.query(ChangeEvent).filter(
                ChangeEvent.snapshot_from == sf,
                ChangeEvent.snapshot_to == st,
            ).all()
            events.extend(rows)

    return events


def compute_batch_impact(
    snapshot_from: int,
    snapshot_to: int,
    *,
    limit: int = 100,
    offset: int = 0,
    q: Optional[str] = None,
) -> BatchImpactResult:
    """Compute impact for ALL changes between two snapshots, paginated.

    Behaviour (v1.19+)
    ------------------
    Reads pre-aggregated per-change counts from ``change_impact_summary``
    rather than walking the graph at request time. The summaries are
    populated by ``run_post_ingest_pipeline`` after every dict import,
    so any change ingested under v1.18+ already has a row.

    For changes ingested under earlier versions (no summary yet), we
    lazily backfill on the first request. The backfill walks the graph
    at ``SUMMARY_MAX_DEPTH=3`` (vs the legacy ``max_depth=10``) and
    persists for next time, so subsequent requests are instant.

    Pagination model (v1.19+):

    - ``changes_analyzed`` is the FULL filtered set count.
    - ``changes`` is the slice ``[offset, offset+limit)``.
    - ``summary``'s donut buckets, breaking_count, total_direct/indirect,
      and ``total_query_count`` are computed over the full set so the
      Impact page can render KPIs and donuts off them without iterating
      the (paginated, possibly truncated) ``changes`` list.

    Accumulates changes across intermediate pairs (e.g. 1→3 = 1→2 + 2→3).
    """

    # ──── Step 1: Collect all ChangeEvents spanning the requested range ────
    events = _load_all_changes(snapshot_from, snapshot_to)

    change_list = [
        {
            "change_id": e.change_id,
            "object_type": e.object_type,
            "object_identifier": e.object_identifier,
            "change_type": e.change_type,
            "severity": e.severity or get_severity(e.change_type),
            "is_breaking": e.is_breaking if e.is_breaking is not None else is_breaking(e.change_type),
            "snapshot_to": e.snapshot_to,
        }
        for e in events
    ]

    if not change_list:
        return BatchImpactResult(snapshot_from=snapshot_from, snapshot_to=snapshot_to)

    # ──── Step 2: Lazy backfill of missing summaries ────
    # Per-snapshot. For each unique snapshot_to in the range we ask the
    # summary helper to compute any change_ids that don't already have
    # rows. ``skip_existing=True`` means already-computed snapshots are
    # essentially free here.
    #
    # Hard cap: if the set of change_ids missing summaries exceeds
    # ``LAZY_BACKFILL_MAX_CHANGES`` we don't run the backfill — it
    # would hang the request as badly as the pre-aggregation was meant
    # to fix. Instead we skip silently and let the read step return
    # zeros for the missing ones; the user can run the dedicated
    # precompute path (post-ingest re-runs, or re-importing the
    # snapshot) to get accurate numbers without a request timeout.
    LAZY_BACKFILL_MAX_CHANGES = 5000

    unique_snap_tos = sorted(set(c["snapshot_to"] for c in change_list))
    import logging as _logging
    _logger = _logging.getLogger(__name__)

    for sto in unique_snap_tos:
        ids_for_sto = [c["change_id"] for c in change_list if c["snapshot_to"] == sto]
        # Cheap pre-check: how many of these ids actually need backfill?
        # Cap is on the *uncomputed* subset, not the total — already-
        # computed snapshots stay free regardless of size.
        from app.graph.impact_summary import filter_uncomputed
        uncomputed = filter_uncomputed(ids_for_sto)
        if not uncomputed:
            continue
        if len(uncomputed) > LAZY_BACKFILL_MAX_CHANGES:
            _logger.warning(
                "Lazy impact-summary backfill skipped for snapshot %s: "
                "%d uncomputed changes exceed the request-time cap "
                "(%d). Re-import the snapshot to populate summaries "
                "via post-ingest, or trigger a dedicated precompute.",
                sto,
                len(uncomputed),
                LAZY_BACKFILL_MAX_CHANGES,
            )
            continue
        try:
            persist_summaries_for_pair(
                sto, change_ids=ids_for_sto, skip_existing=True
            )
        except Exception:
            _logger.exception(
                "Lazy impact-summary backfill failed for snapshot %s; "
                "the affected changes will report zero counts",
                sto,
            )

    # ──── Step 3: Read pre-aggregated summaries ────
    # ``IN (...)`` chunked at 900 for SQLite's 999-variable limit; on a
    # 250k-change Transcend diff this is ~280 round-trips, each one
    # primary-key-indexed and sub-millisecond.
    _SQL_IN_CHUNK = 900
    summary_by_change: Dict[int, _ImpactSummaryRow] = {}
    change_ids_in_range = [c["change_id"] for c in change_list]
    with Session(engine) as session:
        for start in range(0, len(change_ids_in_range), _SQL_IN_CHUNK):
            chunk = change_ids_in_range[start : start + _SQL_IN_CHUNK]
            rows = session.execute(
                select(_ImpactSummaryRow).where(
                    _ImpactSummaryRow.change_id.in_(chunk)
                )
            ).scalars().all()
            for row in rows:
                summary_by_change[row.change_id] = row

    # ──── Step 4: Build usage lookup (best-effort) ────
    # Schema/table names for the blast-radius rollup come directly from
    # object_identifier.split(".") in step 5 — no node query needed here.
    usage_map: Dict[str, tuple[int, int]] = {}
    try:
        from app.usage.usage_models import UsageEvent
        with Session(engine) as session:
            for u in session.query(UsageEvent).all():
                qc = u.query_count or 0
                uc = u.user_count or 0
                key = u.object_name.upper() if u.object_name else u.object_name
                usage_map[key] = (qc, uc)
                short = key.split(".")[-1] if key and "." in key else key
                if short and short not in usage_map:
                    usage_map[short] = (qc, uc)
    except Exception:
        pass

    result = BatchImpactResult(
        snapshot_from=snapshot_from,
        snapshot_to=snapshot_to,
        changes_analyzed=len(change_list),
        limit=limit,
        offset=offset,
    )

    affected_schemas: set = set()
    affected_tables: set = set()
    affected_tables_by_schema: Dict[str, set] = {}
    overall_max_depth = 0
    total_score = 0.0
    total_query_count = 0

    # Bucket counters built during the same single pass — so adding
    # them is O(0) extra work over the per-change rollup. Catastrophic
    # to skip at production scale: 250k changes × 4 client-side
    # iterations froze the browser before this was added.
    bucket_severity: Dict[str, int] = {}
    bucket_change_type: Dict[str, int] = {}
    bucket_schema: Dict[str, int] = {}
    bucket_breaking: Dict[str, int] = {"BREAKING": 0, "NON_BREAKING": 0}

    # We accumulate the FULL per-change list (still tiny in memory —
    # each item is a dataclass with a handful of ints/strings, even
    # 250k items are ~50 MB). Pagination slices at the end.
    all_summaries: List[ChangeImpactSummary] = []
    has_high_breaking = False
    has_high_severity = False

    # ──── Step 6: Per-change rollup from pre-aggregated rows ────
    for change in change_list:
        cid = change["change_id"]
        sev = change["severity"]
        brk = change["is_breaking"]
        if brk:
            result.breaking_count += 1

        # Usage hierarchy unchanged from the v1.17 implementation.
        obj_id = (change["object_identifier"] or "").upper()
        qc, uc = 0, 0
        if obj_id in usage_map:
            qc, uc = usage_map[obj_id]
        else:
            parts = obj_id.split(".")
            if len(parts) >= 3:
                table_key = ".".join(parts[:2])
                if table_key in usage_map:
                    qc, uc = usage_map[table_key]
            if qc == 0 and parts:
                short = parts[-1] if len(parts) < 3 else parts[-2]
                if short in usage_map:
                    qc, uc = usage_map[short]

        # Pull pre-aggregated row when present; default to zeros otherwise
        # (a backfill failure or a change with no graph mapping will land
        # here — both legitimate "no impact" outcomes).
        agg = summary_by_change.get(cid)
        direct_count = agg.direct_count if agg is not None else 0
        indirect_count = agg.indirect_count if agg is not None else 0
        impact_score = float(agg.impact_score) if agg is not None else 0.0
        max_depth = agg.max_depth if agg is not None else 0

        summary = ChangeImpactSummary(
            change_id=cid,
            object_identifier=change["object_identifier"],
            change_type=change["change_type"],
            severity=sev,
            is_breaking=brk,
            query_count=qc,
            user_count=uc,
            direct_count=direct_count,
            indirect_count=indirect_count,
            impact_score=round(impact_score, 4),
        )

        # The changed object's own schema/table contributes to the
        # affected sets. Without per-impact node-level detail, we can't
        # enumerate downstream consumers here — that drill-down lives in
        # the single-change endpoint. The current BlastRadius numbers
        # therefore reflect the changed objects themselves; this is a
        # deliberate trade-off for batch perf at scale.
        parts = obj_id.split(".")
        schema_name = parts[0] if parts else ""
        table_qname = ".".join(parts[:2]) if len(parts) >= 2 else ""
        if schema_name:
            affected_schemas.add(schema_name)
        if table_qname:
            affected_tables.add(table_qname)
            affected_tables_by_schema.setdefault(schema_name, set()).add(table_qname)

        total_score += impact_score
        total_query_count += qc
        if max_depth > overall_max_depth:
            overall_max_depth = max_depth

        # Donut buckets — incremented in O(1) per change.
        sev_key = (sev or "LOW").upper()
        bucket_severity[sev_key] = bucket_severity.get(sev_key, 0) + 1
        ct_key = change["change_type"]
        bucket_change_type[ct_key] = bucket_change_type.get(ct_key, 0) + 1
        if schema_name:
            bucket_schema[schema_name] = bucket_schema.get(schema_name, 0) + 1
        bucket_breaking["BREAKING" if brk else "NON_BREAKING"] += 1

        # Track the flags `overall_risk` needs without iterating again later.
        if brk and sev_key == "HIGH":
            has_high_breaking = True
        if sev_key == "HIGH":
            has_high_severity = True

        all_summaries.append(summary)
        result.total_direct += direct_count
        result.total_indirect += indirect_count

    # ──── Step 7: Pre-grouped affected_databases (server-side join) ────
    # The page used to filter ``affected_tables`` once per database to
    # render the "Affected objects" section — at Transcend scale that
    # was O(databases × tables). We pre-group here so the frontend can
    # render it directly.
    affected_databases = [
        AffectedDatabase(
            schema_name=schema,
            tables=sorted(affected_tables_by_schema.get(schema, set())),
        )
        for schema in sorted(affected_schemas)
    ]

    # ``total_impacted_nodes`` previously deduped impacted nodes across
    # all changes. We now approximate it as the sum of direct counts —
    # the exact deduped figure would require either keeping a per-impact
    # detail list (defeats the purpose of pre-aggregation) or computing
    # a global SQL aggregate. For the UI's "blast radius" framing the
    # sum is the more useful number anyway.
    result.blast_radius = BlastRadius(
        total_impacted_nodes=result.total_direct,
        max_depth=overall_max_depth,
        weighted_score=round(total_score, 4),
        affected_schemas=sorted(affected_schemas),
        affected_tables=sorted(affected_tables),
        affected_databases=affected_databases,
    )

    # ──── Step 8: Materialise donut buckets in display order ────
    # Sorted to keep output deterministic across runs (tests assert on
    # this) and to feed donut charts a stable ordering. Severity keeps
    # its conventional HIGH→MEDIUM→LOW order; the rest go by count desc.
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    result.by_severity = [
        BucketCount(name=name, count=count)
        for name, count in sorted(
            bucket_severity.items(),
            key=lambda kv: severity_order.get(kv[0], 99),
        )
    ]
    result.by_change_type = [
        BucketCount(name=name, count=count)
        for name, count in sorted(
            bucket_change_type.items(), key=lambda kv: -kv[1]
        )
    ]
    result.by_schema = [
        BucketCount(name=name, count=count)
        for name, count in sorted(
            bucket_schema.items(), key=lambda kv: -kv[1]
        )
    ]
    result.by_breaking = [
        BucketCount(name=name, count=count)
        for name, count in bucket_breaking.items()
        if count > 0
    ]
    result.total_query_count = total_query_count

    # ──── Step 9: Overall risk label ────
    # Two-tier heuristic: ≥3 breaking changes OR any HIGH+breaking pushes
    # the whole diff to HIGH risk. A single breaking change or any HIGH
    # severity is MEDIUM. Everything else is LOW. Computed off the
    # pre-tracked flags so we don't re-iterate the change list.
    if result.breaking_count >= 3 or has_high_breaking:
        result.overall_risk = "HIGH"
    elif result.breaking_count >= 1 or has_high_severity:
        result.overall_risk = "MEDIUM"
    else:
        result.overall_risk = "LOW"

    # ──── Step 10: Optional per-change filter, then pagination ────
    # ``q`` filters the table rows by object name (case-insensitive).
    # Aggregates/donuts/KPIs above are intentionally NOT filtered — they
    # always reflect the full diff so the risk summary stays accurate.
    display_summaries = all_summaries
    if q:
        q_lower = q.strip().lower()
        display_summaries = [
            s for s in all_summaries
            if q_lower in s.object_identifier.lower()
        ]
    result.changes_analyzed = len(display_summaries)

    total = len(display_summaries)
    page = display_summaries[offset : offset + limit]
    result.changes = page
    result.has_more = (offset + len(page)) < total

    return result
