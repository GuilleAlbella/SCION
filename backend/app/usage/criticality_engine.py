"""Criticality scoring engine.

Combines usage frequency with graph metrics (out_degree / fragility)
to produce a criticality level per object.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.graph.graph_models import GraphNode
from app.usage.usage_models import ObjectCriticality, UsageEvent


def compute_criticality(
    snapshot_id: int,
    force: bool = False,
    usage_available: bool = True,
) -> List[Dict[str, Any]]:
    """Compute criticality scores scoped to objects that exist in this snapshot.

    Only objects present in the snapshot's graph are included. Usage data
    is matched by object_name. This ensures different snapshots show
    different criticality results reflecting their actual structure.

    Args:
        usage_available: Toggle for the "usage-out-of-scope" fallback mode
            (v1.08 addition, related to the open Chris-level decision on
            whether usage data is delivered in Phase 1 or Phase 2). When
            False, we skip the usage aggregation entirely and compute
            `combined_score = graph_score`. The HIGH/MEDIUM/LOW thresholds
            stay at 0.6 / 0.3 so the UI bands are unchanged — users just
            see graph-driven rankings instead of usage-weighted ones.
            Default True preserves legacy behaviour.
    """

    # ──── Step 1: Cache check (unless force=True) ────
    # Criticality is snapshot-scoped and deterministic, so if we already
    # computed it for this snapshot we return the stored rows immediately.
    # `force=True` is the escape hatch for re-runs after a usage backfill.
    #
    # The read uses the ``ix_object_criticality_snapshot_score`` composite
    # index added in v1.15.00, so even on a 337k-row Transcend snapshot
    # the query plan is an indexed scan in score order — no full sort,
    # no temp table. The full result set is still loaded so callers that
    # need every row (e.g. the criticality CSV exporter) keep working;
    # the API endpoint slices to top-N before serialising.
    with Session(engine) as session:
        if not force:
            existing = session.scalar(
                select(func.count()).select_from(ObjectCriticality)
                .where(ObjectCriticality.snapshot_id == snapshot_id)
            )
            if existing and existing > 0:
                rows = session.query(ObjectCriticality).filter(
                    ObjectCriticality.snapshot_id == snapshot_id
                ).order_by(ObjectCriticality.combined_score.desc()).all()

                return [
                    {
                        "object_name": r.object_name,
                        "usage_score": r.usage_score,
                        "graph_score": r.graph_score,
                        "combined_score": r.combined_score,
                        "criticality_level": r.criticality_level,
                    }
                    for r in rows
                ]

    # ──── Step 2: Clear stale rows on forced recompute ────
    # We physically delete rather than upsert: the set of objects in the
    # snapshot may have shrunk, and leaving orphan criticality rows would
    # skew downstream aggregates in intelligence_metrics.
    # If forcing, clear old data for this snapshot
    if force:
        with Session(engine) as session:
            with session.begin():
                session.query(ObjectCriticality).filter(
                    ObjectCriticality.snapshot_id == snapshot_id
                ).delete()

    # ──── Step 3: Define the scoring universe from the snapshot's graph ────
    # Scoping by graph nodes (not by usage events) is deliberate: we only
    # rank objects that actually exist in this snapshot. Otherwise a dropped
    # table would keep appearing in criticality rankings forever.
    # Load graph nodes for THIS snapshot — these define the scope
    with Session(engine) as session:
        nodes = session.query(GraphNode).filter(
            GraphNode.snapshot_id == snapshot_id
        ).all()

    # The "fragility" metadata is a pre-computed graph-based score
    # (how structurally central / risky this node is) produced by
    # graph_metrics. Nodes without it default to 0 so their graph_score
    # is purely from degree/usage, not inflated.
    snapshot_objects: Dict[str, float] = {}
    for node in nodes:
        meta = node.node_metadata or {}
        snapshot_objects[node.object_name] = meta.get("fragility", 0.0)

    if not snapshot_objects:
        return []

    # ──── Step 4: Aggregate usage across all events (all snapshots) ────
    # Usage events are not snapshot-scoped — they represent the raw query
    # log. We aggregate across all time and match by object_name. This
    # means a table's usage score reflects its TOTAL observed traffic,
    # not just traffic coincident with a particular snapshot.
    # Load usage data (aggregate by object_name).
    # When `usage_available=False` we skip this entirely — the scoring
    # loop below notices an empty usage_map and collapses to graph-only.
    usage_map: Dict[str, int] = {}
    max_queries = 1
    if usage_available:
        with Session(engine) as session:
            usage_agg = session.execute(
                select(
                    UsageEvent.object_name,
                    func.sum(UsageEvent.query_count).label("total_queries"),
                    func.max(UsageEvent.user_count).label("max_users"),
                )
                .group_by(UsageEvent.object_name)
            ).all()

        # We track the max in the same pass we fill the map so we can later
        # normalize each object's usage to [0.0, 1.0] relative to the busiest
        # object in the system (min-max scaling). Starting max_queries at 1
        # avoids divide-by-zero in the fully-empty case.
        for obj_name, total_q, _ in usage_agg:
            usage_map[obj_name] = total_q or 0
            if (total_q or 0) > max_queries:
                max_queries = total_q

    # Scope: only objects that exist in this snapshot
    all_objects = set(snapshot_objects.keys())

    results: List[Dict[str, Any]] = []

    # ──── Step 5: Score each object and persist (bulk path) ────
    # Core formula (usage_available=True):
    #   combined = 0.6 * usage_score + 0.4 * graph_score
    # Fallback formula (usage_available=False, v1.08):
    #   combined = graph_score
    #   — used when usage data is out-of-scope for Phase 1. Rankings
    #     reflect pure structural centrality (graph fragility). Same
    #     0.6 / 0.3 bands so the Criticality page doesn't need UI
    #     changes.
    # The 60/40 default split favors usage because a table nobody
    # queries is rarely business-critical even if the graph says it's
    # central.
    #
    # Scale note: at production scale this loop runs ~240k times. The
    # original code did `session.add(ObjectCriticality(...))` per
    # iteration, which grows the SQLAlchemy identity map linearly and
    # makes the trailing flush proportional to N². We now collect plain
    # dicts and ship them in batches with `bulk_insert_mappings` —
    # constant-time per row, identity map stays empty, ~5-10× faster
    # on SQLite for our row shape.
    rows_to_insert: list[dict] = []
    for obj_name in sorted(all_objects):
        queries = usage_map.get(obj_name, 0)
        usage_score = round(queries / max_queries, 4) if max_queries > 0 else 0.0
        graph_score = round(snapshot_objects.get(obj_name, 0.0), 4)
        if usage_available:
            combined = round(0.6 * usage_score + 0.4 * graph_score, 4)
        else:
            combined = graph_score

        if combined >= 0.6:
            level = "HIGH"
        elif combined >= 0.3:
            level = "MEDIUM"
        else:
            level = "LOW"

        rows_to_insert.append({
            "object_name": obj_name,
            "snapshot_id": snapshot_id,
            "usage_score": usage_score,
            "graph_score": graph_score,
            "combined_score": combined,
            "criticality_level": level,
        })

        results.append({
            "object_name": obj_name,
            "usage_score": usage_score,
            "graph_score": graph_score,
            "combined_score": combined,
            "criticality_level": level,
        })

    if rows_to_insert:
        with Session(engine) as session:
            with session.begin():
                for i in range(0, len(rows_to_insert), _BULK_INSERT_BATCH_SIZE):
                    session.bulk_insert_mappings(
                        ObjectCriticality,
                        rows_to_insert[i:i + _BULK_INSERT_BATCH_SIZE],
                    )

    results.sort(key=lambda r: r["combined_score"], reverse=True)
    return results


# Same rationale as the bulk-insert helpers in dict_persister and
# graph_metrics: small enough to stay well under SQLite's 32 766
# host-parameter cap, big enough to amortise per-statement overhead.
_BULK_INSERT_BATCH_SIZE = 5000
