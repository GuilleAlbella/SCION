from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.diff.diff_engine import DiffEngine
from app.diff.diff_models import ChangeEvent
from app.graph.graph_builder import build_graph_for_snapshot
from app.graph.graph_diff_linker import link_changes_to_graph
from app.graph.graph_models import GraphNode


def _reset_graph_and_diff_state() -> None:
    """Best-effort cleanup of graph and diff state between tests."""

    with Session(engine) as session:
        session.query(ChangeEvent).delete()
        session.query(GraphNode).delete()
        session.query(TableSnapshot).delete()
        session.query(SchemaSnapshot).delete()
        session.query(Snapshot).delete()
        session.commit()


def _create_two_snapshots_with_table_change() -> tuple[int, int]:
    """Create two snapshots where the second adds a table.

    Returns (snapshot_from, snapshot_to).
    """

    with Session(engine) as session:
        # First snapshot: no tables in schema "public".
        snap1 = Snapshot(
            snapshot_time=datetime(2024, 1, 1, tzinfo=UTC),
            source_system="test",
            description="snap1",
            is_baseline=False,
        )
        session.add(snap1)
        session.flush()

        schema1 = SchemaSnapshot(
            snapshot_id=snap1.snapshot_id,
            schema_name="public",
        )
        session.add(schema1)
        session.flush()

        # Second snapshot: same schema + one table.
        snap2 = Snapshot(
            snapshot_time=datetime(2024, 1, 2, tzinfo=UTC),
            source_system="test",
            description="snap2",
            is_baseline=False,
        )
        session.add(snap2)
        session.flush()

        schema2 = SchemaSnapshot(
            snapshot_id=snap2.snapshot_id,
            schema_name="public",
        )
        session.add(schema2)
        session.flush()

        table2 = TableSnapshot(
            schema_id=schema2.schema_id,
            table_name="users",
            object_type="TABLE",
        )
        session.add(table2)

        session.commit()

        return snap1.snapshot_id, snap2.snapshot_id


def test_change_event_is_linked_to_correct_graph_node() -> None:
    """Diff events for snapshot_to should map to the proper graph_node."""

    _reset_graph_and_diff_state()

    snapshot_from, snapshot_to = _create_two_snapshots_with_table_change()

    # Run diff to produce change_event rows.
    diff_engine = DiffEngine()
    changes = diff_engine.compute_diff(snapshot_from, snapshot_to)
    assert changes, "Expected at least one change event for added table"

    # Build graph for snapshot_to so that graph_node rows exist.
    build_graph_for_snapshot(snapshot_to)

    # Now link change events to graph nodes.
    mapping = link_changes_to_graph(snapshot_to)

    assert mapping, "Expected at least one linked change -> graph node"

    with Session(engine) as session:
        # Find the TABLE_ADDED event for public.users.
        event = (
            session.query(ChangeEvent)
            .filter(
                ChangeEvent.snapshot_to == snapshot_to,
                ChangeEvent.object_type == "TABLE",
                ChangeEvent.object_identifier == "public.users",
            )
            .one()
        )

        node_id = mapping.get(event.change_id)
        assert node_id is not None

        node = session.get(GraphNode, node_id)
        assert node is not None
        assert node.object_type == "TABLE"
        assert node.object_name == "public.users"
        assert node.snapshot_id == snapshot_to


def test_unmatched_change_event_does_not_fail() -> None:
    """Events without a corresponding graph node must not break execution."""

    _reset_graph_and_diff_state()

    with Session(engine) as session:
        snap = Snapshot(
            snapshot_time=datetime(2024, 1, 3, tzinfo=UTC),
            source_system="test",
            description="snap-unmatched",
            is_baseline=False,
        )
        session.add(snap)
        session.flush()

        snapshot_id = snap.snapshot_id

        event = ChangeEvent(
            snapshot_from=snap.snapshot_id,
            snapshot_to=snap.snapshot_id,
            object_type="TABLE",
            object_identifier="nonexistent.schema.table",
            change_type="TABLE_ADDED",
            before_state=None,
            after_state=None,
        )
        session.add(event)
        session.commit()

    # No graph_node rows for this snapshot; linker should return an empty
    # mapping and not raise.
    mapping = link_changes_to_graph(snapshot_id)
    assert mapping == {}


def test_linker_is_snapshot_isolated() -> None:
    """Linking for one snapshot must not mix events from another snapshot."""

    _reset_graph_and_diff_state()

    # Create two independent pairs of snapshots with different table names.
    with Session(engine) as session:
        # Pair A
        snap1a = Snapshot(
            snapshot_time=datetime(2024, 1, 1, tzinfo=UTC),
            source_system="test",
            description="snap1a",
            is_baseline=False,
        )
        session.add(snap1a)
        session.flush()

        schema1a = SchemaSnapshot(
            snapshot_id=snap1a.snapshot_id,
            schema_name="public",
        )
        session.add(schema1a)
        session.flush()

        snap2a = Snapshot(
            snapshot_time=datetime(2024, 1, 2, tzinfo=UTC),
            source_system="test",
            description="snap2a",
            is_baseline=False,
        )
        session.add(snap2a)
        session.flush()

        schema2a = SchemaSnapshot(
            snapshot_id=snap2a.snapshot_id,
            schema_name="public",
        )
        session.add(schema2a)
        session.flush()

        table2a = TableSnapshot(
            schema_id=schema2a.schema_id,
            table_name="users_a",
            object_type="TABLE",
        )
        session.add(table2a)

        # Pair B
        snap1b = Snapshot(
            snapshot_time=datetime(2024, 2, 1, tzinfo=UTC),
            source_system="test",
            description="snap1b",
            is_baseline=False,
        )
        session.add(snap1b)
        session.flush()

        schema1b = SchemaSnapshot(
            snapshot_id=snap1b.snapshot_id,
            schema_name="public",
        )
        session.add(schema1b)
        session.flush()

        snap2b = Snapshot(
            snapshot_time=datetime(2024, 2, 2, tzinfo=UTC),
            source_system="test",
            description="snap2b",
            is_baseline=False,
        )
        session.add(snap2b)
        session.flush()

        schema2b = SchemaSnapshot(
            snapshot_id=snap2b.snapshot_id,
            schema_name="public",
        )
        session.add(schema2b)
        session.flush()

        table2b = TableSnapshot(
            schema_id=schema2b.schema_id,
            table_name="users_b",
            object_type="TABLE",
        )
        session.add(table2b)

        session.commit()

        snapshot_from_a, snapshot_to_a = snap1a.snapshot_id, snap2a.snapshot_id
        snapshot_from_b, snapshot_to_b = snap1b.snapshot_id, snap2b.snapshot_id

    # Produce diffs and graphs for both pairs.
    diff_engine = DiffEngine()
    diff_engine.compute_diff(snapshot_from_a, snapshot_to_a)
    diff_engine.compute_diff(snapshot_from_b, snapshot_to_b)

    build_graph_for_snapshot(snapshot_to_a)
    build_graph_for_snapshot(snapshot_to_b)

    mapping_a = link_changes_to_graph(snapshot_to_a)
    mapping_b = link_changes_to_graph(snapshot_to_b)

    assert mapping_a
    assert mapping_b

    # Ensure that mappings are disjoint by change_id.
    assert set(mapping_a.keys()).isdisjoint(mapping_b.keys())


def test_linker_is_readonly_and_deterministic() -> None:
    """Running the linker multiple times must be read-only and deterministic."""

    _reset_graph_and_diff_state()

    snapshot_from, snapshot_to = _create_two_snapshots_with_table_change()

    diff_engine = DiffEngine()
    diff_engine.compute_diff(snapshot_from, snapshot_to)
    build_graph_for_snapshot(snapshot_to)

    with Session(engine) as session:
        before_events = session.query(ChangeEvent).count()
        before_nodes = session.query(GraphNode).count()

    first = link_changes_to_graph(snapshot_to)
    second = link_changes_to_graph(snapshot_to)

    assert first == second

    with Session(engine) as session:
        after_events = session.query(ChangeEvent).count()
        after_nodes = session.query(GraphNode).count()

    # No rows should have been added or removed by the linker.
    assert before_events == after_events
    assert before_nodes == after_nodes
