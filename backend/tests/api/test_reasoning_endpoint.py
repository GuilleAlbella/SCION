from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1 import v1_router
from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.diff.diff_models import ChangeEvent
from app.graph.graph_models import GraphEdge, GraphNode
from app.graph.impact_models import ImpactEvent
from app.taisa.taisa_models import ReasoningEvent


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app wiring the v1 API router.

    This app is used only to exercise the reasoning endpoint. It does not
    register extra middleware or dependencies beyond the versioned router.
    """

    app = FastAPI()
    app.include_router(v1_router)
    return app


def _reset_reasoning_state() -> None:
    """Clear reasoning, impact, graph, change, and snapshot tables."""

    with Session(engine) as session:
        session.query(ReasoningEvent).delete()
        session.query(ImpactEvent).delete()
        session.query(GraphEdge).delete()
        session.query(GraphNode).delete()
        session.query(ChangeEvent).delete()
        session.query(Snapshot).delete()
        session.commit()


def _seed_change_snapshot_and_impact(with_impact: bool = True) -> int:
    """Create minimal Snapshot, ChangeEvent, and optional ImpactEvent.

    Returns the created change_id.
    """

    with Session(engine) as session:
        snapshot = Snapshot(
            snapshot_time=__import__("datetime").datetime.now(__import__("datetime").UTC),
            source_system="test-system",
            description="Reasoning API test snapshot",
            is_baseline=False,
        )
        session.add(snapshot)
        session.flush()

        change = ChangeEvent(
            snapshot_from=snapshot.snapshot_id - 1 if snapshot.snapshot_id else 0,
            snapshot_to=snapshot.snapshot_id,
            object_type="TABLE",
            object_identifier="public.users",
            change_type="TABLE_CHANGED",
            before_state={"columns": ["id"]},
            after_state={"columns": ["id", "email"]},
        )
        session.add(change)
        session.flush()

        if with_impact:
            node = GraphNode(
                object_type="TABLE",
                object_name="public.users",
                snapshot_id=snapshot.snapshot_id,
            )
            session.add(node)
            session.flush()

            impact = ImpactEvent(
                change_id=change.change_id,
                impacted_node_id=node.node_id,
                impact_level="DIRECT",
                depth=1,
                snapshot_id=snapshot.snapshot_id,
            )
            session.add(impact)

        session.commit()

        return change.change_id


def _count_reasoning_events_for_change(change_id: int) -> int:
    with Session(engine) as session:
        return session.query(ReasoningEvent).filter(ReasoningEvent.change_id == change_id).count()


def test_reasoning_endpoint_happy_path() -> None:
    _reset_reasoning_state()

    app = _create_test_app()
    client = TestClient(app)

    change_id = _seed_change_snapshot_and_impact(with_impact=True)

    response = client.post(f"/api/v1/reasoning/{change_id}")
    assert response.status_code == 201

    payload = response.json()
    assert payload["change_id"] == change_id
    assert isinstance(payload["classification"], str)
    assert payload["classification"] != ""
    assert isinstance(payload["risk_level"], str)
    assert payload["risk_level"] != ""

    # ReasoningEvent must have been persisted.
    assert _count_reasoning_events_for_change(change_id) == 1


def test_reasoning_endpoint_allows_empty_impact_list() -> None:
    _reset_reasoning_state()

    app = _create_test_app()
    client = TestClient(app)

    change_id = _seed_change_snapshot_and_impact(with_impact=False)

    response = client.post(f"/api/v1/reasoning/{change_id}")
    assert response.status_code == 201

    payload = response.json()
    assert payload["change_id"] == change_id
    assert _count_reasoning_events_for_change(change_id) == 1


def test_reasoning_endpoint_rejects_unknown_change_id() -> None:
    _reset_reasoning_state()

    app = _create_test_app()
    client = TestClient(app)

    response = client.post("/api/v1/reasoning/999999")
    assert response.status_code == 404

    payload = response.json()
    assert "change_id does not exist" in payload["detail"]


def test_reasoning_endpoint_rejects_non_integer_change_id() -> None:
    _reset_reasoning_state()

    app = _create_test_app()
    client = TestClient(app)

    response = client.post("/api/v1/reasoning/not-an-int")
    # FastAPI will return 422 for invalid path parameter type.
    assert response.status_code == 422


def test_reasoning_endpoint_can_be_executed_multiple_times() -> None:
    _reset_reasoning_state()

    app = _create_test_app()
    client = TestClient(app)

    change_id = _seed_change_snapshot_and_impact(with_impact=True)

    response1 = client.post(f"/api/v1/reasoning/{change_id}")
    assert response1.status_code == 201

    response2 = client.post(f"/api/v1/reasoning/{change_id}")
    assert response2.status_code == 201

    # Two reasoning events should exist for the same change_id.
    assert _count_reasoning_events_for_change(change_id) == 2
