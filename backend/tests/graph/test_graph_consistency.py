from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.diff.diff_models import ChangeEvent
from app.graph.consistency_checks import (
    validate_graph_snapshot_isolation,
    validate_impact_snapshot_alignment,
    validate_no_cross_snapshot_edges,
)
from app.graph.graph_models import GraphEdge, GraphNode
from app.graph.impact_models import ImpactEvent


def _reset_graph_and_impact_state() -> None:
    with Session(engine) as session:
        session.query(ImpactEvent).delete()
        session.query(GraphEdge).delete()
        session.query(GraphNode).delete()
        session.query(TableSnapshot).delete()
        session.query(SchemaSnapshot).delete()
        session.query(Snapshot).delete()
        session.query(ChangeEvent).delete()
        session.commit()


def test_graph_snapshot_isolation_valid() -> None:
    _reset_graph_and_impact_state()

    snapshot_id = 1
    with Session(engine) as session:
        snap = Snapshot(
            snapshot_time=datetime(2024, 1, 1, tzinfo=UTC),
            source_system="test",
            description="snap1",
            is_baseline=False,
        )
        session.add(snap)
        session.flush()

        schema = SchemaSnapshot(snapshot_id=snap.snapshot_id, schema_name="public")
        session.add(schema)
        session.flush()

        table = TableSnapshot(
            schema_id=schema.schema_id,
            table_name="a",
            object_type="TABLE",
        )
        session.add(table)
        session.flush()

        n1 = GraphNode(object_type="TABLE", object_name="A", snapshot_id=snap.snapshot_id)
        n2 = GraphNode(object_type="TABLE", object_name="B", snapshot_id=snap.snapshot_id)
        session.add_all([n1, n2])
        session.flush()

        e = GraphEdge(
            source_node_id=n1.node_id,
            target_node_id=n2.node_id,
            relationship_type="DEPENDS_ON",
            snapshot_id=snap.snapshot_id,
        )
        session.add(e)
        session.commit()

    # Should not raise for a consistent snapshot.
    validate_graph_snapshot_isolation(snapshot_id)
    validate_no_cross_snapshot_edges(snapshot_id)


def test_cross_snapshot_edge_raises_error() -> None:
    _reset_graph_and_impact_state()

    with Session(engine) as session:
        # Snapshot 1
        snap1 = Snapshot(
            snapshot_time=datetime(2024, 1, 1, tzinfo=UTC),
            source_system="test",
            description="snap1",
            is_baseline=False,
        )
        session.add(snap1)
        session.flush()

        n1 = GraphNode(object_type="TABLE", object_name="A", snapshot_id=snap1.snapshot_id)
        session.add(n1)

        # Snapshot 2
        snap2 = Snapshot(
            snapshot_time=datetime(2024, 1, 2, tzinfo=UTC),
            source_system="test",
            description="snap2",
            is_baseline=False,
        )
        session.add(snap2)
        session.flush()

        n2 = GraphNode(object_type="TABLE", object_name="B", snapshot_id=snap2.snapshot_id)
        session.add(n2)
        session.flush()

        # Edge claims to belong to snapshot1 but connects to node in snapshot2.
        e = GraphEdge(
            source_node_id=n1.node_id,
            target_node_id=n2.node_id,
            relationship_type="DEPENDS_ON",
            snapshot_id=snap1.snapshot_id,
        )
        session.add(e)
        session.commit()

        snap1_id = snap1.snapshot_id

    try:
        validate_no_cross_snapshot_edges(snap1_id)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for cross-snapshot edge")


def test_impact_snapshot_alignment_valid() -> None:
    _reset_graph_and_impact_state()

    with Session(engine) as session:
        snap = Snapshot(
            snapshot_time=datetime(2024, 3, 1, tzinfo=UTC),
            source_system="test",
            description="snap-impact",
            is_baseline=False,
        )
        session.add(snap)
        session.flush()

        node = GraphNode(
            object_type="TABLE",
            object_name="T",
            snapshot_id=snap.snapshot_id,
        )
        session.add(node)
        session.flush()

        change = ChangeEvent(
            snapshot_from=snap.snapshot_id,
            snapshot_to=snap.snapshot_id,
            object_type="TABLE",
            object_identifier="T",
            change_type="TABLE_ADDED",
            before_state=None,
            after_state=None,
        )
        session.add(change)
        session.flush()

        impact = ImpactEvent(
            change_id=change.change_id,
            impacted_node_id=node.node_id,
            impact_level="DIRECT",
            depth=1,
            snapshot_id=snap.snapshot_id,
        )
        session.add(impact)
        session.commit()

        change_id = change.change_id
        snapshot_id = snap.snapshot_id

    # Should not raise when everything is aligned on snapshot_id.
    validate_impact_snapshot_alignment(change_id=change_id, snapshot_id=snapshot_id)


def test_impact_snapshot_alignment_raises_on_mismatch() -> None:
    _reset_graph_and_impact_state()

    with Session(engine) as session:
        snap1 = Snapshot(
            snapshot_time=datetime(2024, 4, 1, tzinfo=UTC),
            source_system="test",
            description="snap1",
            is_baseline=False,
        )
        snap2 = Snapshot(
            snapshot_time=datetime(2024, 4, 2, tzinfo=UTC),
            source_system="test",
            description="snap2",
            is_baseline=False,
        )
        session.add_all([snap1, snap2])
        session.flush()

        node = GraphNode(
            object_type="TABLE",
            object_name="T2",
            snapshot_id=snap2.snapshot_id,
        )
        session.add(node)
        session.flush()

        change = ChangeEvent(
            snapshot_from=snap1.snapshot_id,
            snapshot_to=snap1.snapshot_id,
            object_type="TABLE",
            object_identifier="T2",
            change_type="TABLE_ADDED",
            before_state=None,
            after_state=None,
        )
        session.add(change)
        session.flush()

        impact = ImpactEvent(
            change_id=change.change_id,
            impacted_node_id=node.node_id,
            impact_level="DIRECT",
            depth=1,
            snapshot_id=snap1.snapshot_id,
        )
        session.add(impact)
        session.commit()

        change_id = change.change_id
        snapshot_id = snap1.snapshot_id

    try:
        validate_impact_snapshot_alignment(change_id=change_id, snapshot_id=snapshot_id)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for misaligned impact snapshot")


def test_multiple_snapshots_coexist_without_conflict() -> None:
    _reset_graph_and_impact_state()

    with Session(engine) as session:
        # Snapshot A
        snap_a = Snapshot(
            snapshot_time=datetime(2024, 5, 1, tzinfo=UTC),
            source_system="test",
            description="snapA",
            is_baseline=False,
        )
        snap_b = Snapshot(
            snapshot_time=datetime(2024, 5, 2, tzinfo=UTC),
            source_system="test",
            description="snapB",
            is_baseline=False,
        )
        session.add_all([snap_a, snap_b])
        session.flush()

        node_a = GraphNode(
            object_type="TABLE",
            object_name="Ta",
            snapshot_id=snap_a.snapshot_id,
        )
        node_b = GraphNode(
            object_type="TABLE",
            object_name="Tb",
            snapshot_id=snap_b.snapshot_id,
        )
        session.add_all([node_a, node_b])
        session.flush()

        edge_a = GraphEdge(
            source_node_id=node_a.node_id,
            target_node_id=node_a.node_id,
            relationship_type="DEPENDS_ON",
            snapshot_id=snap_a.snapshot_id,
        )
        edge_b = GraphEdge(
            source_node_id=node_b.node_id,
            target_node_id=node_b.node_id,
            relationship_type="DEPENDS_ON",
            snapshot_id=snap_b.snapshot_id,
        )
        session.add_all([edge_a, edge_b])
        session.commit()

        snap_a_id = snap_a.snapshot_id
        snap_b_id = snap_b.snapshot_id

    # Validations for both snapshots should not raise.
    validate_graph_snapshot_isolation(snap_a_id)
    validate_graph_snapshot_isolation(snap_b_id)
