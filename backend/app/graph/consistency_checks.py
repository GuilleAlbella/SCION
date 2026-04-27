from __future__ import annotations

from typing import Dict, List, Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent
from app.graph.graph_models import GraphEdge, GraphNode
from app.graph.impact_models import ImpactEvent


def validate_graph_snapshot_isolation(snapshot_id: int) -> None:
    """Validate that graph state for a snapshot is isolated and consistent.

    Checks:
    - All GraphEdge rows with the given snapshot_id connect nodes that also
      belong to the same snapshot.
    - All GraphNode instances referenced by those edges share the same
      snapshot_id.
    """

    if snapshot_id is None:
        raise ValueError("snapshot_id must not be None")

    with Session(engine) as session:
        _validate_no_cross_snapshot_edges_internal(session, snapshot_id)


def validate_no_cross_snapshot_edges(snapshot_id: int) -> None:
    """Ensure that edges do not cross snapshot boundaries for a snapshot.

    For all GraphEdge rows with the given snapshot_id:
    - source_node.snapshot_id == snapshot_id
    - target_node.snapshot_id == snapshot_id
    - Both node snapshot_ids are equal to each other and to edge.snapshot_id.
    """

    if snapshot_id is None:
        raise ValueError("snapshot_id must not be None")

    with Session(engine) as session:
        _validate_no_cross_snapshot_edges_internal(session, snapshot_id)


def _validate_no_cross_snapshot_edges_internal(session: Session, snapshot_id: int) -> None:
    edges = session.scalars(
        select(GraphEdge).where(GraphEdge.snapshot_id == snapshot_id)
    ).all()

    if not edges:
        return

    node_ids: Set[int] = set()
    for edge in edges:
        node_ids.add(edge.source_node_id)
        node_ids.add(edge.target_node_id)

    nodes = session.scalars(
        select(GraphNode).where(GraphNode.node_id.in_(node_ids))
    ).all()
    nodes_by_id = {n.node_id: n for n in nodes}

    for edge in edges:
        src = nodes_by_id.get(edge.source_node_id)
        tgt = nodes_by_id.get(edge.target_node_id)

        if src is None or tgt is None:
            raise ValueError(
                "GraphEdge references nodes that do not exist for snapshot "
                f"{snapshot_id}: edge_id={edge.edge_id}"
            )

        if src.snapshot_id != snapshot_id or tgt.snapshot_id != snapshot_id:
            raise ValueError(
                "Cross-snapshot edge detected: "
                f"edge.snapshot_id={edge.snapshot_id}, "
                f"source.snapshot_id={src.snapshot_id}, "
                f"target.snapshot_id={tgt.snapshot_id}"
            )

        if src.snapshot_id != tgt.snapshot_id:
            raise ValueError(
                "Edge connects nodes belonging to different snapshots: "
                f"source.snapshot_id={src.snapshot_id}, "
                f"target.snapshot_id={tgt.snapshot_id}"
            )


def validate_impact_snapshot_alignment(change_id: int, snapshot_id: int) -> None:
    """Validate alignment between impact events, change_event, and graph nodes.

    Checks for the given (change_id, snapshot_id):
    - All ImpactEvent.snapshot_id == snapshot_id.
    - The corresponding ChangeEvent has snapshot_to == snapshot_id.
    - All impacted GraphNode rows have snapshot_id == snapshot_id.
    """

    if change_id is None or snapshot_id is None:
        raise ValueError("change_id and snapshot_id must not be None")

    with Session(engine) as session:
        impacts = session.scalars(
            select(ImpactEvent).where(
                ImpactEvent.change_id == change_id,
                ImpactEvent.snapshot_id == snapshot_id,
            )
        ).all()

        if not impacts:
            # No persisted impact for this pair; treat as trivially consistent.
            return

        # Validate snapshot_id on impact rows (defensive, should all match).
        for impact in impacts:
            if impact.snapshot_id != snapshot_id:
                raise ValueError(
                    "ImpactEvent has mismatched snapshot_id: "
                    f"expected={snapshot_id}, actual={impact.snapshot_id}"
                )

        change_event = session.get(ChangeEvent, change_id)
        if change_event is None:
            raise ValueError(
                f"No ChangeEvent found for change_id={change_id} while "
                "validating impact alignment."
            )

        if change_event.snapshot_to != snapshot_id:
            raise ValueError(
                "ChangeEvent.snapshot_to does not match impact snapshot_id: "
                f"expected={snapshot_id}, actual={change_event.snapshot_to}"
            )

        impacted_ids: Set[int] = {impact.impacted_node_id for impact in impacts}
        nodes = session.scalars(
            select(GraphNode).where(GraphNode.node_id.in_(impacted_ids))
        ).all()
        nodes_by_id = {n.node_id: n for n in nodes}

        for impact in impacts:
            node = nodes_by_id.get(impact.impacted_node_id)
            if node is None:
                raise ValueError(
                    "ImpactEvent references a GraphNode that does not exist: "
                    f"node_id={impact.impacted_node_id}"
                )

            if node.snapshot_id != snapshot_id:
                raise ValueError(
                    "ImpactEvent/GraphNode snapshot mismatch: "
                    f"impact.snapshot_id={impact.snapshot_id}, "
                    f"node.snapshot_id={node.snapshot_id}"
                )


def detect_cycles(snapshot_id: int) -> List[List[int]]:
    """Detect cycles in the graph for a given snapshot.

    Returns a list of cycles, where each cycle is a list of node_ids.
    Empty list means no cycles (DAG).
    """

    with Session(engine) as session:
        edges = session.scalars(
            select(GraphEdge).where(GraphEdge.snapshot_id == snapshot_id)
        ).all()

        nodes = session.scalars(
            select(GraphNode).where(GraphNode.snapshot_id == snapshot_id)
        ).all()

    # Build adjacency list
    adj: Dict[int, List[int]] = {n.node_id: [] for n in nodes}
    for edge in edges:
        if edge.source_node_id in adj:
            adj[edge.source_node_id].append(edge.target_node_id)

    # DFS-based cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[int, int] = {nid: WHITE for nid in adj}
    cycles: List[List[int]] = []
    path: List[int] = []

    def dfs(node: int) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in adj.get(node, []):
            if color.get(neighbor) == GRAY:
                # Found cycle: extract it from path
                idx = path.index(neighbor)
                cycles.append(path[idx:] + [neighbor])
            elif color.get(neighbor) == WHITE:
                dfs(neighbor)
        path.pop()
        color[node] = BLACK

    for node_id in adj:
        if color[node_id] == WHITE:
            dfs(node_id)

    return cycles
