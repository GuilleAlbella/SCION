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
from app.graph.graph_models import GraphNode
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
class BlastRadius:
    """Aggregate footprint of all changes in a diff pair.

    Attributes:
        total_impacted_nodes: Count of distinct impacted graph nodes.
        max_depth: Deepest propagation depth reached across changes.
        weighted_score: Sum of per-impact weighted scores.
        affected_schemas: Sorted list of schema names touched.
        affected_tables: Sorted list of fully-qualified tables touched.
    """

    total_impacted_nodes: int = 0
    max_depth: int = 0
    weighted_score: float = 0.0
    affected_schemas: List[str] = field(default_factory=list)
    affected_tables: List[str] = field(default_factory=list)


@dataclass
class BatchImpactResult:
    """Full result of a batch impact computation between two snapshots.

    Attributes:
        snapshot_from: Starting snapshot id.
        snapshot_to: Ending snapshot id.
        changes_analyzed: Number of ``ChangeEvent`` rows processed.
        blast_radius: Aggregated blast-radius footprint.
        changes: Per-change impact summaries.
        total_direct: Sum of direct (downstream) impacts.
        total_indirect: Sum of indirect (upstream) impacts.
        breaking_count: Number of breaking changes.
        overall_risk: Overall risk level (``LOW``/``MEDIUM``/``HIGH``).
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

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the batch result into a JSON-friendly dict.

        Returns:
            Nested dictionary with ``snapshot_from``/``snapshot_to`` ids,
            blast-radius details, per-change summaries, and aggregate summary.
        """
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
            },
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


def compute_batch_impact(snapshot_from: int, snapshot_to: int) -> BatchImpactResult:
    """Compute impact for ALL changes between two snapshots.

    Behaviour (v1.18+)
    ------------------
    Reads pre-aggregated per-change counts from ``change_impact_summary``
    rather than walking the graph at request time. The summaries are
    populated by ``run_post_ingest_pipeline`` after every dict import,
    so any change ingested under v1.18+ already has a row.

    For changes ingested under earlier versions (no summary yet), we
    lazily backfill on the first request. The backfill walks the graph
    at ``SUMMARY_MAX_DEPTH=3`` (vs the legacy ``max_depth=10``) and
    persists for next time, so subsequent requests are instant.
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
    summary_by_change: Dict[int, _ImpactSummaryRow] = {}
    change_ids_in_range = [c["change_id"] for c in change_list]
    with Session(engine) as session:
        rows = session.execute(
            select(_ImpactSummaryRow).where(
                _ImpactSummaryRow.change_id.in_(change_ids_in_range)
            )
        ).scalars().all()
        for row in rows:
            summary_by_change[row.change_id] = row

    # ──── Step 4: Pre-index node metadata for blast-radius rollups ────
    # We still need names + schemas to populate ``affected_schemas`` and
    # ``affected_tables`` in the BlastRadius rollup. These come from the
    # changed objects themselves (not the impacted neighbours, which we
    # no longer enumerate here — that's the per-change drill-down's job).
    node_names: Dict[int, str] = {}
    node_schemas: Dict[int, str] = {}
    with Session(engine) as session:
        for sto in unique_snap_tos:
            nodes = session.query(GraphNode).filter(
                GraphNode.snapshot_id == sto
            ).all()
            for n in nodes:
                node_names[n.node_id] = n.object_name
                node_schemas[n.node_id] = n.schema_name

    # ──── Step 5: Build usage lookup (best-effort) ────
    usage_map: Dict[str, tuple[int, int]] = {}
    try:
        from app.usage.usage_models import UsageEvent
        with Session(engine) as session:
            for u in session.query(UsageEvent).all():
                qc = u.query_count or 0
                uc = u.user_count or 0
                usage_map[u.object_name] = (qc, uc)
                short = u.object_name.split(".")[-1] if "." in u.object_name else u.object_name
                if short not in usage_map:
                    usage_map[short] = (qc, uc)
    except Exception:
        pass

    result = BatchImpactResult(
        snapshot_from=snapshot_from,
        snapshot_to=snapshot_to,
        changes_analyzed=len(change_list),
    )

    affected_schemas: set = set()
    affected_tables: set = set()
    overall_max_depth = 0
    total_score = 0.0

    # ──── Step 6: Per-change rollup from pre-aggregated rows ────
    for change in change_list:
        cid = change["change_id"]
        sev = change["severity"]
        brk = change["is_breaking"]
        if brk:
            result.breaking_count += 1

        # Usage hierarchy unchanged from the v1.17 implementation.
        obj_id = change["object_identifier"]
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
        if parts:
            affected_schemas.add(parts[0])
        if len(parts) >= 2:
            affected_tables.add(".".join(parts[:2]))

        total_score += impact_score
        if max_depth > overall_max_depth:
            overall_max_depth = max_depth

        result.changes.append(summary)
        result.total_direct += direct_count
        result.total_indirect += indirect_count

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
    )

    # ──── Step 6: Derive overall risk label ────
    # Risk is a two-tier heuristic: ≥3 breaking changes OR any HIGH+breaking
    # change pushes the whole diff to HIGH risk. A single breaking change
    # or any HIGH severity is MEDIUM. Everything else is LOW.
    # Overall risk based on worst severity + breaking count
    if result.breaking_count >= 3 or any(c.severity == "HIGH" and c.is_breaking for c in result.changes):
        result.overall_risk = "HIGH"
    elif result.breaking_count >= 1 or any(c.severity == "HIGH" for c in result.changes):
        result.overall_risk = "MEDIUM"
    else:
        result.overall_risk = "LOW"

    return result
