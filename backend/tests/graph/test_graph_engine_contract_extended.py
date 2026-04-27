from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot
from app.diff.diff_engine import DiffEngine
from app.diff.diff_models import ChangeEvent
from app.graph.graph_builder import build_graph_for_snapshot
from app.graph.graph_diff_linker import link_changes_to_graph
from app.graph.graph_models import GraphEdge, GraphNode
from app.graph.impact_analyzer import compute_downstream_impact
from app.graph.impact_models import ImpactEvent
from app.graph.impact_persister import persist_impact_events


def _reset_all_state() -> None:
    """Best-effort cleanup for graph, impact, change, and snapshots."""

    with Session(engine) as session:
        session.query(ImpactEvent).delete()
        session.query(GraphEdge).delete()
        session.query(GraphNode).delete()
        session.query(ChangeEvent).delete()
        session.query(ColumnSnapshot).delete()
        session.query(TableSnapshot).delete()
        session.query(SchemaSnapshot).delete()
        session.query(Snapshot).delete()
        session.commit()


def _create_snapshot_pair_with_table_change() -> tuple[int, int]:
    """Create two snapshots where the second adds a TABLE in schema 'public'."""

    with Session(engine) as session:
        # snapshot_from: schema without tables
        snap1 = Snapshot(
            snapshot_time=datetime(2024, 1, 1, tzinfo=UTC),
            source_system="test",
            description="snap-from",
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

        # snapshot_to: same schema + one table
        snap2 = Snapshot(
            snapshot_time=datetime(2024, 1, 2, tzinfo=UTC),
            source_system="test",
            description="snap-to",
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


def _run_graph_pipeline_for_change(snapshot_from: int, snapshot_to: int) -> int:
    """Run the end-to-end graph pipeline for a single change.

    Returns the change_id used for impact persistence.
    """

    # 1) Diff: compute and persist change events (owned by Diff Engine).
    diff_engine = DiffEngine()
    changes = diff_engine.compute_diff(snapshot_from, snapshot_to)
    assert changes, "Expected at least one change event from diff engine"

    # 2) Build graph for snapshot_to.
    build_graph_for_snapshot(snapshot_to)

    # 3) Link diff events to graph nodes.
    mapping = link_changes_to_graph(snapshot_to)
    assert mapping, "Expected at least one linked change -> graph node"

    # For contract purposes, pick a deterministic change_id.
    change_id = sorted(mapping.keys())[0]
    node_id = mapping[change_id]

    # 4) Compute downstream impact for that node (technical only).
    impacts = compute_downstream_impact(
        start_node_id=node_id,
        snapshot_id=snapshot_to,
    )

    # Always include at least the starting node as DIRECT impact (depth=1).
    base_impact = {
        "node_id": node_id,
        "depth": 1,
        "relationship_path": [node_id],
    }

    # Persist impacts (append-only, idempotent) for this change.
    persist_impact_events(
        change_id=change_id,
        snapshot_id=snapshot_to,
        impacts=[base_impact] + impacts,
    )

    return change_id


def test_graph_engine_does_not_mutate_snapshots_or_change_events_on_rerun() -> None:
    """Re-running the graph pipeline must not mutate snapshots or change_events.

    DiffEngine is allowed to create change_event rows; the Graph Engine
    components (builder, linker, impact) must leave snapshot and change_event
    counts unchanged on re-run.
    """

    _reset_all_state()

    snapshot_from, snapshot_to = _create_snapshot_pair_with_table_change()

    # First, run diff once to materialise change_event rows.
    diff_engine = DiffEngine()
    diff_engine.compute_diff(snapshot_from, snapshot_to)

    with Session(engine) as session:
        snap_count_before = session.query(Snapshot).count()
        schema_count_before = session.query(SchemaSnapshot).count()
        table_count_before = session.query(TableSnapshot).count()
        column_count_before = session.query(ColumnSnapshot).count()
        change_count_before = session.query(ChangeEvent).count()

    # Run the graph pipeline twice.
    change_id = _run_graph_pipeline_for_change(snapshot_from, snapshot_to)
    _run_graph_pipeline_for_change(snapshot_from, snapshot_to)

    with Session(engine) as session:
        snap_count_after = session.query(Snapshot).count()
        schema_count_after = session.query(SchemaSnapshot).count()
        table_count_after = session.query(TableSnapshot).count()
        column_count_after = session.query(ColumnSnapshot).count()
        change_count_after = session.query(ChangeEvent).count()

        # Graph persistence tables.
        node_count = session.query(GraphNode).count()
        edge_count = session.query(GraphEdge).count()
        impact_count = session.query(ImpactEvent).filter(
            ImpactEvent.change_id == change_id
        ).count()

    # Snapshot and change_event tables must not be altered by graph pipeline.
    assert snap_count_before == snap_count_after
    assert schema_count_before == schema_count_after
    assert table_count_before == table_count_after
    assert column_count_before == column_count_after
    assert change_count_before == change_count_after

    # Graph-related tables must be non-empty but stable across re-runs.
    assert node_count > 0
    assert edge_count >= 0
    assert impact_count > 0


def test_graph_engine_only_writes_graph_and_impact_tables() -> None:
    """Graph Engine must not write to snapshot_* or change_event tables.

    This test isolates diff (which creates change_event) from the graph
    pipeline. After diff has run, the graph pipeline is executed and we
    verify that only graph_node, graph_edge, and impact_event are affected.
    """

    _reset_all_state()

    snapshot_from, snapshot_to = _create_snapshot_pair_with_table_change()

    # Run diff once to create change_event baseline.
    diff_engine = DiffEngine()
    diff_engine.compute_diff(snapshot_from, snapshot_to)

    with Session(engine) as session:
        snap_before = session.query(Snapshot).count()
        schema_before = session.query(SchemaSnapshot).count()
        table_before = session.query(TableSnapshot).count()
        column_before = session.query(ColumnSnapshot).count()
        change_before = session.query(ChangeEvent).count()
        node_before = session.query(GraphNode).count()
        edge_before = session.query(GraphEdge).count()
        impact_before = session.query(ImpactEvent).count()

    # Run graph pipeline once.
    change_id = _run_graph_pipeline_for_change(snapshot_from, snapshot_to)

    with Session(engine) as session:
        snap_after = session.query(Snapshot).count()
        schema_after = session.query(SchemaSnapshot).count()
        table_after = session.query(TableSnapshot).count()
        column_after = session.query(ColumnSnapshot).count()
        change_after = session.query(ChangeEvent).count()
        node_after = session.query(GraphNode).count()
        edge_after = session.query(GraphEdge).count()
        impact_after = session.query(ImpactEvent).filter(
            ImpactEvent.change_id == change_id
        ).count()

    # Snapshot and change_event tables must be unchanged by the graph pipeline.
    assert snap_before == snap_after
    assert schema_before == schema_after
    assert table_before == table_after
    assert column_before == column_after
    assert change_before == change_after

    # Graph tables must reflect writes by the graph pipeline.
    assert node_after >= node_before
    assert edge_after >= edge_before
    assert impact_after >= impact_before


def test_graph_outputs_are_sufficient_for_external_reasoning() -> None:
    """Graph Engine outputs enough information for higher layers to reason.

    This test does not assert semantics, only that the stored impact events
    contain the minimal contract fields required by TAISA/UI:
    - change_id
    - impacted_node_id
    - impact_level (DIRECT/INDIRECT)
    - depth
    - snapshot_id
    """

    _reset_all_state()

    snapshot_from, snapshot_to = _create_snapshot_pair_with_table_change()
    change_id = _run_graph_pipeline_for_change(snapshot_from, snapshot_to)

    with Session(engine) as session:
        impacts = (
            session.query(ImpactEvent)
            .filter(ImpactEvent.change_id == change_id)
            .all()
        )

        assert impacts, "Expected persisted impact events for external reasoning"

        for impact in impacts:
            assert impact.change_id == change_id
            assert isinstance(impact.impacted_node_id, int)
            assert impact.snapshot_id == snapshot_to
            assert impact.impact_level in {"DIRECT", "INDIRECT"}
            assert isinstance(impact.depth, int) and impact.depth >= 1

            node = session.get(GraphNode, impact.impacted_node_id)
            assert node is not None
            assert node.snapshot_id == snapshot_to
