from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.engine import engine
from app.graph.graph_models import GraphNode
from app.graph.impact_models import ImpactEvent
from app.graph.impact_persister import persist_impact_events


def _reset_impact_state() -> None:
    with Session(engine) as session:
        session.query(ImpactEvent).delete()
        session.query(GraphNode).delete()
        session.commit()


def _create_graph_node(snapshot_id: int, name: str) -> int:
    with Session(engine) as session:
        node = GraphNode(
            object_type="TABLE",
            object_name=name,
            snapshot_id=snapshot_id,
        )
        session.add(node)
        session.commit()
        return node.node_id


def test_persists_direct_and_indirect_impacts() -> None:
    _reset_impact_state()

    snapshot_id = 100
    node_direct = _create_graph_node(snapshot_id, "direct")
    node_indirect = _create_graph_node(snapshot_id, "indirect")

    impacts = [
        {"node_id": node_direct, "depth": 1, "relationship_path": [1, 2]},
        {"node_id": node_indirect, "depth": 2, "relationship_path": [1, 2, 3]},
    ]

    change_id = 123
    persist_impact_events(change_id=change_id, snapshot_id=snapshot_id, impacts=impacts)

    with Session(engine) as session:
        rows = (
            session.query(ImpactEvent)
            .filter(ImpactEvent.change_id == change_id)
            .order_by(ImpactEvent.impact_id)
            .all()
        )

        assert len(rows) == 2

        levels = {row.impact_level for row in rows}
        depths = {row.depth for row in rows}
        snapshots = {row.snapshot_id for row in rows}

        assert levels == {"DIRECT", "INDIRECT"}
        assert depths == {1, 2}
        assert snapshots == {snapshot_id}

        for row in rows:
            assert row.detected_at is not None


def test_idempotency_per_change_and_snapshot() -> None:
    _reset_impact_state()

    snapshot_id = 101
    node = _create_graph_node(snapshot_id, "table1")

    impacts = [
        {"node_id": node, "depth": 1, "relationship_path": [node]},
    ]

    change_id = 200
    persist_impact_events(change_id=change_id, snapshot_id=snapshot_id, impacts=impacts)
    persist_impact_events(change_id=change_id, snapshot_id=snapshot_id, impacts=impacts)

    with Session(engine) as session:
        rows = session.query(ImpactEvent).filter(ImpactEvent.change_id == change_id).all()
        assert len(rows) == 1


def test_persistence_isolated_by_change_id() -> None:
    _reset_impact_state()

    snapshot_id = 102
    node = _create_graph_node(snapshot_id, "table2")

    impacts = [
        {"node_id": node, "depth": 1, "relationship_path": [node]},
    ]

    persist_impact_events(change_id=1, snapshot_id=snapshot_id, impacts=impacts)
    persist_impact_events(change_id=2, snapshot_id=snapshot_id, impacts=impacts)

    with Session(engine) as session:
        rows_change1 = session.query(ImpactEvent).filter(ImpactEvent.change_id == 1).all()
        rows_change2 = session.query(ImpactEvent).filter(ImpactEvent.change_id == 2).all()

        assert len(rows_change1) == 1
        assert len(rows_change2) == 1


def test_rollback_on_error() -> None:
    _reset_impact_state()

    snapshot_id = 103
    node = _create_graph_node(snapshot_id, "table3")

    # First, persist a valid event so that we have a baseline count.
    valid_impacts = [
        {"node_id": node, "depth": 1, "relationship_path": [node]},
    ]

    change_id = 300
    persist_impact_events(
        change_id=change_id,
        snapshot_id=snapshot_id,
        impacts=valid_impacts,
    )

    with Session(engine) as session:
        before_count = session.query(ImpactEvent).count()

    # Now attempt to persist a set of impacts that will trigger an error
    # (invalid depth), ensuring that no partial rows are committed.
    bad_impacts = [
        {"node_id": node, "depth": 0, "relationship_path": [node]},
    ]

    try:
        persist_impact_events(
            change_id=change_id + 1,
            snapshot_id=snapshot_id,
            impacts=bad_impacts,
        )
    except ValueError:
        pass

    with Session(engine) as session:
        after_count = session.query(ImpactEvent).count()

    assert before_count == after_count
