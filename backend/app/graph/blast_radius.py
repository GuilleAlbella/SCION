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
from app.graph.graph_diff_linker import link_changes_to_graph
from app.graph.graph_models import GraphNode
from app.graph.impact_analyzer import compute_downstream_impact, compute_upstream_impact
from app.graph.impact_persister import persist_impact_events


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

    Accumulates changes across intermediate pairs (e.g. 1→3 = 1→2 + 2→3).
    """

    # ──── Step 1: Collect all ChangeEvents spanning the requested range ────
    events = _load_all_changes(snapshot_from, snapshot_to)

    # Flatten ORM rows into plain dicts. severity/is_breaking may be NULL on
    # legacy rows predating v5.2 — fall back to the static classifier to keep
    # old data usable without a backfill migration.
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

    # ──── Step 2: Resolve each change to its graph node ────
    # Each ChangeEvent needs its corresponding GraphNode id so we can walk
    # downstream/upstream edges. The mapping is per-snapshot because node ids
    # are NOT stable across snapshots (a table has a new node row each snap).
    # Link changes to graph nodes — per snapshot_to
    unique_snap_tos = set(c["snapshot_to"] for c in change_list)
    mapping: Dict[int, int] = {}
    for sto in unique_snap_tos:
        partial = link_changes_to_graph(sto)
        mapping.update(partial)

    # ──── Step 3: Pre-index node metadata for aggregate fields ────
    # We need (name, schema) for each impacted node id to build the
    # affected_schemas / affected_tables aggregates later. Pre-indexing avoids
    # an N+1 query pattern inside the main loop.
    # Build node name lookup across all relevant snapshots
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

    # ──── Step 4: Build usage lookup (best-effort) ────
    # Usage data is optional — it enriches the summary but is not required
    # for impact analysis. The whole block is wrapped in try/except so a
    # missing usage_event table (e.g. in a minimal dev DB) doesn't blow up
    # the blast-radius calculation.
    # Build usage lookup: object_identifier → (query_count, user_count)
    # We match on full qualified name AND on short name (for COLUMN changes).
    usage_map: Dict[str, tuple[int, int]] = {}
    try:
        from app.usage.usage_models import UsageEvent
        with Session(engine) as session:
            for u in session.query(UsageEvent).all():
                qc = u.query_count or 0
                uc = u.user_count or 0
                usage_map[u.object_name] = (qc, uc)
                # Also map the short name for fallback matching
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

    all_impacted_node_ids: set = set()
    all_schemas: set = set()
    all_tables: set = set()
    max_depth = 0
    total_score = 0.0

    # ──── Step 5: Per-change impact walk + aggregation ────
    # For each change we: (a) look up usage, (b) walk the graph downstream
    # and upstream, (c) persist ImpactEvents, (d) accumulate global stats.
    for change in change_list:
        cid = change["change_id"]
        node_id = mapping.get(cid)

        sev = change["severity"]
        brk = change["is_breaking"]
        if brk:
            result.breaking_count += 1

        # Usage match is hierarchical because usage is almost never tracked
        # at column granularity. For a column change "schema.table.col" we
        # try the full id first, then fall back to the parent table, and
        # finally to a bare short name. This maximizes hit rate without
        # mis-attributing usage across unrelated objects.
        # Look up usage data: first try full identifier (e.g. schema.table),
        # then the table portion (e.g. schema.table for a COLUMN change),
        # then the short name.
        obj_id = change["object_identifier"]
        qc, uc = 0, 0
        if obj_id in usage_map:
            qc, uc = usage_map[obj_id]
        else:
            parts = obj_id.split(".")
            # For schema.table.column, try schema.table
            if len(parts) >= 3:
                table_key = ".".join(parts[:2])
                if table_key in usage_map:
                    qc, uc = usage_map[table_key]
            if qc == 0 and parts:
                short = parts[-1] if len(parts) < 3 else parts[-2]
                if short in usage_map:
                    qc, uc = usage_map[short]

        summary = ChangeImpactSummary(
            change_id=cid,
            object_identifier=change["object_identifier"],
            change_type=change["change_type"],
            severity=sev,
            is_breaking=brk,
            query_count=qc,
            user_count=uc,
        )

        if node_id is not None:
            # max_depth=10 is an empirical cap: deeper traversals rarely add
            # signal (impact_score ≤ 0.1) and can explode on dense graphs.
            sto = change["snapshot_to"]
            downstream = compute_downstream_impact(node_id, sto, max_depth=10)
            upstream = compute_upstream_impact(node_id, sto, max_depth=10)
            all_impacts = downstream + upstream

            if all_impacts:
                persist_impact_events(change_id=cid, snapshot_id=sto, impacts=all_impacts)

            # Convention in SCION: "direct" == downstream consumers (what
            # actually breaks when this object changes), "indirect" ==
            # upstream producers (what this object depends on). This mapping
            # differs from the raw graph-depth semantics.
            summary.direct_count = len(downstream)
            summary.indirect_count = len(upstream)

            for imp in all_impacts:
                nid = imp["node_id"]
                # Deduplicate: the same node may be reached from multiple
                # changes but should count as ONE impacted node for the
                # blast-radius total.
                all_impacted_node_ids.add(nid)
                depth = imp["depth"]
                # impact_score = 1/depth (directly hit = 1.0, 2 hops = 0.5…).
                # This decay reflects that distant dependencies are less
                # likely to break in practice than direct consumers.
                score = imp.get("impact_score", 1.0 / depth)
                total_score += score
                if depth > max_depth:
                    max_depth = depth

                name = node_names.get(nid, "")
                schema = node_schemas.get(nid, "")
                if schema:
                    all_schemas.add(schema)
                if name and "." in name:
                    all_tables.add(name)

            summary.impact_score = round(
                sum(imp.get("impact_score", 0) for imp in all_impacts), 4
            )

        result.changes.append(summary)
        result.total_direct += summary.direct_count
        result.total_indirect += summary.indirect_count

    result.blast_radius = BlastRadius(
        total_impacted_nodes=len(all_impacted_node_ids),
        max_depth=max_depth,
        weighted_score=round(total_score, 4),
        affected_schemas=sorted(all_schemas),
        affected_tables=sorted(all_tables),
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
