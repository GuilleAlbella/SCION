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
    """Compute metrics and store them in node_metadata JSON. Returns count updated."""

    metrics = compute_node_metrics(snapshot_id)

    with Session(engine) as session:
        with session.begin():
            count = 0
            for node_id, m in metrics.items():
                node = session.get(GraphNode, node_id)
                if node is None:
                    continue
                existing = node.node_metadata or {}
                existing.update(asdict(m))
                node.node_metadata = existing
                count += 1
    return count
