from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.graph.graph_models import GraphEdge, GraphNode


def _get_inspector():
    return inspect(engine)


def test_graph_tables_exist_after_migrations() -> None:
    """Alembic migrations must create graph_node and graph_edge tables."""

    inspector = _get_inspector()
    tables = set(inspector.get_table_names())

    assert "graph_node" in tables
    assert "graph_edge" in tables


def test_can_insert_graph_node() -> None:
    """A basic GraphNode row can be inserted and committed without error."""

    with Session(engine) as session:
        node = GraphNode(
            object_type="TABLE",
            object_name="public.users",
            snapshot_id=1,
            node_metadata={"example": True},
        )
        session.add(node)
        session.commit()

        assert node.node_id is not None


def test_can_insert_graph_edge_and_query_by_snapshot() -> None:
    """GraphEdge rows can be inserted and queried by snapshot_id."""

    with Session(engine) as session:
        node_a = GraphNode(
            object_type="TABLE",
            object_name="public.orders",
            snapshot_id=2,
        )
        node_b = GraphNode(
            object_type="TABLE",
            object_name="public.order_items",
            snapshot_id=2,
        )
        session.add_all([node_a, node_b])
        session.flush()

        edge = GraphEdge(
            source_node_id=node_a.node_id,
            target_node_id=node_b.node_id,
            relationship_type="DEPENDS_ON",
            snapshot_id=2,
        )
        session.add(edge)
        session.commit()

        edges = (
            session.query(GraphEdge)
            .filter(GraphEdge.snapshot_id == 2)
            .all()
        )

        assert any(e.edge_id == edge.edge_id for e in edges)


def test_commit_and_rollback_behave_normally() -> None:
    """Simple transactions with GraphNode/GraphEdge should commit and rollback.

    This test does not exercise any business logic; it only ensures that
    the models participate in SQLAlchemy transactions without errors.
    """

    with Session(engine) as session:
        node = GraphNode(
            object_type="VIEW",
            object_name="analytics.report",
            snapshot_id=3,
        )
        session.add(node)
        session.commit()

        first_id = node.node_id

        # Now attempt to add and rollback a second node.
        node2 = GraphNode(
            object_type="TABLE",
            object_name="analytics.staging_report",
            snapshot_id=3,
        )
        session.add(node2)
        session.flush()
        second_id = node2.node_id
        session.rollback()

        # After rollback, the second node should not be present.
        remaining_ids = [n.node_id for n in session.query(GraphNode).all()]

        assert first_id in remaining_ids
        assert second_id not in remaining_ids
