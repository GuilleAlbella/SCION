from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.engine import engine
from app.graph.graph_models import GraphEdge, GraphNode
from app.graph.impact_analyzer import (
    compute_downstream_impact,
    compute_upstream_impact,
)


def _reset_graph_state() -> None:
    with Session(engine) as session:
        session.query(GraphEdge).delete()
        session.query(GraphNode).delete()
        session.commit()


def _create_linear_chain(snapshot_id: int) -> list[int]:
    """Create a simple linear chain A -> B -> C -> D for a snapshot.

    Returns the list of node_ids in order [A, B, C, D].
    """

    with Session(engine) as session:
        nodes = []
        for name in ["A", "B", "C", "D"]:
            node = GraphNode(
                object_type="TABLE",
                object_name=name,
                snapshot_id=snapshot_id,
            )
            session.add(node)
            session.flush()
            nodes.append(node.node_id)

        # A -> B -> C -> D
        edges = [
            (nodes[0], nodes[1]),
            (nodes[1], nodes[2]),
            (nodes[2], nodes[3]),
        ]
        for src, tgt in edges:
            session.add(
                GraphEdge(
                    source_node_id=src,
                    target_node_id=tgt,
                    relationship_type="DEPENDS_ON",
                    snapshot_id=snapshot_id,
                )
            )

        session.commit()

        return nodes


def test_downstream_direct_and_indirect_impact() -> None:
    _reset_graph_state()

    snapshot_id = 1
    nodes = _create_linear_chain(snapshot_id)
    start = nodes[0]  # A

    impact = compute_downstream_impact(start_node_id=start, snapshot_id=snapshot_id)

    # Expect B, C, D reachable downstream.
    reached = {entry["node_id"] for entry in impact}
    assert reached == set(nodes[1:])

    # Check depths: B at 1, C at 2, D at 3.
    depths = {entry["node_id"]: entry["depth"] for entry in impact}
    assert depths[nodes[1]] == 1
    assert depths[nodes[2]] == 2
    assert depths[nodes[3]] == 3

    # Paths should start at A and end at the corresponding node.
    for entry in impact:
        assert entry["relationship_path"][0] == start
        assert entry["relationship_path"][-1] == entry["node_id"]


def test_upstream_impact() -> None:
    _reset_graph_state()

    snapshot_id = 2
    nodes = _create_linear_chain(snapshot_id)
    start = nodes[3]  # D

    impact = compute_upstream_impact(start_node_id=start, snapshot_id=snapshot_id)

    # Expect C, B, A upstream.
    reached = {entry["node_id"] for entry in impact}
    assert reached == set(nodes[:-1])

    depths = {entry["node_id"]: entry["depth"] for entry in impact}
    assert depths[nodes[2]] == 1
    assert depths[nodes[1]] == 2
    assert depths[nodes[0]] == 3

    for entry in impact:
        assert entry["relationship_path"][0] == entry["node_id"]
        assert entry["relationship_path"][-1] == start


def test_max_depth_limits_results() -> None:
    _reset_graph_state()

    snapshot_id = 3
    nodes = _create_linear_chain(snapshot_id)
    start = nodes[0]  # A

    impact = compute_downstream_impact(
        start_node_id=start,
        snapshot_id=snapshot_id,
        max_depth=2,
    )

    # With max_depth=2, we should only get B (1) and C (2).
    reached = {entry["node_id"] for entry in impact}
    assert reached == {nodes[1], nodes[2]}


def test_snapshot_isolation_in_impact() -> None:
    _reset_graph_state()

    snapshot_1 = 10
    snapshot_2 = 11

    nodes1 = _create_linear_chain(snapshot_1)
    nodes2 = _create_linear_chain(snapshot_2)

    # Downstream from A in snapshot_1 must not see nodes from snapshot_2.
    impact1 = compute_downstream_impact(
        start_node_id=nodes1[0],
        snapshot_id=snapshot_1,
    )

    impact2 = compute_downstream_impact(
        start_node_id=nodes2[0],
        snapshot_id=snapshot_2,
    )

    reached1 = {entry["node_id"] for entry in impact1}
    reached2 = {entry["node_id"] for entry in impact2}

    assert reached1.isdisjoint(reached2)


def test_graph_without_dependencies_returns_empty() -> None:
    _reset_graph_state()

    snapshot_id = 20
    with Session(engine) as session:
        node = GraphNode(
            object_type="TABLE",
            object_name="lonely",
            snapshot_id=snapshot_id,
        )
        session.add(node)
        session.commit()
        start = node.node_id

    downstream = compute_downstream_impact(start_node_id=start, snapshot_id=snapshot_id)
    upstream = compute_upstream_impact(start_node_id=start, snapshot_id=snapshot_id)

    assert downstream == []
    assert upstream == []


def test_cycles_do_not_cause_infinite_loops() -> None:
    _reset_graph_state()

    snapshot_id = 30
    with Session(engine) as session:
        a = GraphNode(object_type="TABLE", object_name="A", snapshot_id=snapshot_id)
        b = GraphNode(object_type="TABLE", object_name="B", snapshot_id=snapshot_id)
        session.add_all([a, b])
        session.flush()

        a_id = a.node_id
        b_id = b.node_id

        # Create a cycle A -> B -> A.
        e1 = GraphEdge(
            source_node_id=a.node_id,
            target_node_id=b.node_id,
            relationship_type="DEPENDS_ON",
            snapshot_id=snapshot_id,
        )
        e2 = GraphEdge(
            source_node_id=b_id,
            target_node_id=a_id,
            relationship_type="DEPENDS_ON",
            snapshot_id=snapshot_id,
        )
        session.add_all([e1, e2])
        session.commit()

    downstream = compute_downstream_impact(start_node_id=a_id, snapshot_id=snapshot_id)
    upstream = compute_upstream_impact(start_node_id=a_id, snapshot_id=snapshot_id)

    # Each direction should see only the other node once.
    assert {entry["node_id"] for entry in downstream} == {b_id}
    assert {entry["node_id"] for entry in upstream} == {b_id}
