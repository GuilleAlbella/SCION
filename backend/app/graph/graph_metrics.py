"""Graph metrics: centrality, fragility, and degree analysis.

Pure read-only functions that compute metrics from persisted graph state
and optionally update node_metadata JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.graph.graph_models import GraphEdge, GraphNode


@dataclass
class NodeMetrics:
    in_degree: int = 0
    out_degree: int = 0
    fragility: float = 0.0
    is_hub: bool = False


def compute_node_metrics(snapshot_id: int) -> Dict[int, NodeMetrics]:
    """Compute in-degree, out-degree, and fragility for all nodes in a snapshot.

    fragility = out_degree / max(total_edges, 1)
      High fragility means many other nodes depend on this one.

    is_hub = in_degree > 2 * average_in_degree
      Hub nodes receive significantly more incoming edges than average.
    """

    with Session(engine) as session:
        nodes = session.scalars(
            select(GraphNode).where(GraphNode.snapshot_id == snapshot_id)
        ).all()

        edges = session.scalars(
            select(GraphEdge).where(GraphEdge.snapshot_id == snapshot_id)
        ).all()

    node_ids = {n.node_id for n in nodes}
    total_edges = max(len(edges), 1)

    # Count degrees
    in_degree: Dict[int, int] = {nid: 0 for nid in node_ids}
    out_degree: Dict[int, int] = {nid: 0 for nid in node_ids}

    for edge in edges:
        if edge.source_node_id in out_degree:
            out_degree[edge.source_node_id] += 1
        if edge.target_node_id in in_degree:
            in_degree[edge.target_node_id] += 1

    avg_in = sum(in_degree.values()) / max(len(in_degree), 1)

    metrics: Dict[int, NodeMetrics] = {}
    for nid in node_ids:
        ind = in_degree.get(nid, 0)
        outd = out_degree.get(nid, 0)
        metrics[nid] = NodeMetrics(
            in_degree=ind,
            out_degree=outd,
            fragility=round(outd / total_edges, 4),
            is_hub=ind > 2 * avg_in,
        )

    return metrics


def persist_node_metrics(snapshot_id: int) -> int:
    """Compute metrics and store them in node_metadata JSON.

    Returns the number of nodes whose metadata was updated.

    Scale note: the previous implementation called `session.get(GraphNode,
    nid)` per node and updated each one through the ORM, which translates
    to one SELECT + one UPDATE per node = ~2N round-trips. For 240k nodes
    that's nearly half a million round-trips and the operation never
    finished within an hour. The current implementation:

      1. Loads the *existing* `node_metadata` for every node in this
         snapshot in a single SELECT — needed to merge fresh metric
         values on top of whatever else lives there (e.g. legacy
         enrichment fields a future pass may have added).
      2. Computes the merged JSON in Python.
      3. Ships the updates with `bulk_update_mappings` in batches of
         5 000 rows. SQLAlchemy emits one UPDATE statement per batch
         using `executemany`, which is what we need at this scale.
    """

    metrics = compute_node_metrics(snapshot_id)
    if not metrics:
        return 0

    # Pre-load existing metadata so we merge instead of overwrite.
    # `node_metadata` is JSON; the ORM hands us either `None` or a
    # plain dict per row. Using a single SELECT here is what makes
    # the rest O(1) per node.
    #
    # Single transaction for both the read and the writes — SQLAlchemy
    # 2.0 autobegins on the first `session.execute(...)` call, so a
    # nested `with session.begin()` would raise "A transaction is
    # already begun on this Session". Wrapping read + write in one
    # `with session.begin()` block sidesteps that.
    with Session(engine) as session:
        with session.begin():
            existing_meta: Dict[int, dict] = {
                node_id: (meta or {})
                for node_id, meta in session.execute(
                    select(GraphNode.node_id, GraphNode.node_metadata)
                    .where(GraphNode.snapshot_id == snapshot_id)
                ).all()
            }

            updates: list[dict] = []
            for node_id, m in metrics.items():
                if node_id not in existing_meta:
                    # Metric refers to a node that's not in this snapshot —
                    # skip rather than insert a phantom row.
                    continue
                merged = dict(existing_meta[node_id])
                merged.update(asdict(m))
                updates.append({"node_id": node_id, "node_metadata": merged})

            if not updates:
                return 0

            for i in range(0, len(updates), _BULK_UPDATE_BATCH_SIZE):
                session.bulk_update_mappings(
                    GraphNode, updates[i:i + _BULK_UPDATE_BATCH_SIZE]
                )
    return len(updates)


# Same rationale as the dict_persister batch size: small enough to keep
# any single SQL statement well under SQLite's 32 766 host-parameter
# cap, big enough to amortise the per-statement overhead. Tuned for
# 240k+ node updates on the Transcend-DevTest extract.
_BULK_UPDATE_BATCH_SIZE = 5000
