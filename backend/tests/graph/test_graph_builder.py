from __future__ import annotations

from sqlalchemy.orm import Session

from datetime import UTC, datetime

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.graph.graph_builder import build_graph_for_snapshot
from app.graph.graph_models import GraphEdge, GraphNode


def _create_snapshot_with_tables(snapshot_marker: int) -> int:
    """Helper to seed a minimal snapshot, schemas, and tables for tests.

    Returns the actual ``snapshot_id`` assigned by the database.
    """

    with Session(engine) as session:
        snapshot = Snapshot(
            snapshot_time=datetime(2024, 1, 1, tzinfo=UTC),
            source_system="test",
            description=f"snapshot-{snapshot_marker}",
            is_baseline=False,
        )
        session.add(snapshot)
        session.flush()

        schema = SchemaSnapshot(
            snapshot_id=snapshot.snapshot_id,
            schema_name="public",
        )
        session.add(schema)
        session.flush()

        table = TableSnapshot(
            schema_id=schema.schema_id,
            table_name="users",
            object_type="TABLE",
        )
        session.add(table)

        session.commit()

        return snapshot.snapshot_id


def test_builds_nodes_and_edges_for_snapshot() -> None:
    """Graph builder should create nodes and edges for a given snapshot."""

    snapshot_id = _create_snapshot_with_tables(1001)

    build_graph_for_snapshot(snapshot_id)

    with Session(engine) as session:
        nodes = (
            session.query(GraphNode)
            .filter(GraphNode.snapshot_id == snapshot_id)
            .all()
        )
        edges = (
            session.query(GraphEdge)
            .filter(GraphEdge.snapshot_id == snapshot_id)
            .all()
        )

        # Expect one schema node and one table node.
        object_types = {n.object_type for n in nodes}
        object_names = {n.object_name for n in nodes}

        assert "SCHEMA" in object_types
        assert "TABLE" in object_types
        assert "public" in object_names
        assert "public.users" in object_names

        # Expect at least one DEPENDS_ON edge from the table to the schema.
        rel_types = {e.relationship_type for e in edges}
        assert "DEPENDS_ON" in rel_types


def test_builder_is_idempotent_for_snapshot() -> None:
    """Running the builder twice for the same snapshot must not duplicate data."""

    snapshot_id = _create_snapshot_with_tables(1002)

    build_graph_for_snapshot(snapshot_id)
    build_graph_for_snapshot(snapshot_id)

    with Session(engine) as session:
        nodes = (
            session.query(GraphNode)
            .filter(GraphNode.snapshot_id == snapshot_id)
            .all()
        )
        edges = (
            session.query(GraphEdge)
            .filter(GraphEdge.snapshot_id == snapshot_id)
            .all()
        )

        # Natural keys must be unique; running twice should not increase counts.
        node_keys = {
            (n.object_type, n.object_name, n.snapshot_id) for n in nodes
        }
        edge_keys = {
            (
                e.source_node_id,
                e.target_node_id,
                e.relationship_type,
                e.snapshot_id,
            )
            for e in edges
        }

        assert len(node_keys) == len(nodes)
        assert len(edge_keys) == len(edges)


def test_graph_isolated_between_snapshots() -> None:
    """Graph for one snapshot must not affect graph for another snapshot."""

    snapshot_a = _create_snapshot_with_tables(2001)
    snapshot_b = _create_snapshot_with_tables(2002)

    build_graph_for_snapshot(snapshot_a)
    build_graph_for_snapshot(snapshot_b)

    with Session(engine) as session:
        nodes_a = (
            session.query(GraphNode)
            .filter(GraphNode.snapshot_id == snapshot_a)
            .all()
        )
        nodes_b = (
            session.query(GraphNode)
            .filter(GraphNode.snapshot_id == snapshot_b)
            .all()
        )

        edges_a = (
            session.query(GraphEdge)
            .filter(GraphEdge.snapshot_id == snapshot_a)
            .all()
        )
        edges_b = (
            session.query(GraphEdge)
            .filter(GraphEdge.snapshot_id == snapshot_b)
            .all()
        )

        assert nodes_a and nodes_b
        assert edges_a and edges_b

        ids_a = {n.node_id for n in nodes_a}
        ids_b = {n.node_id for n in nodes_b}

        assert ids_a.isdisjoint(ids_b)

        edge_snapshots = {e.snapshot_id for e in edges_a + edges_b}
        assert edge_snapshots == {snapshot_a, snapshot_b}
