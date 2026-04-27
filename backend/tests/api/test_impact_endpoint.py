from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1 import v1_router
from app.db.engine import engine
from app.diff.diff_models import ChangeEvent
from app.graph.graph_models import GraphEdge, GraphNode
from app.graph.impact_models import ImpactEvent


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app wiring the v1 API router.

    This app is used only to exercise the impact endpoint. It does not
    register extra middleware or dependencies beyond the versioned router.
    """

    app = FastAPI()
    app.include_router(v1_router)
    return app


def _reset_graph_and_impact_state() -> None:
    """Clear graph, impact, and change_event tables for isolated tests."""

    with Session(engine) as session:
        session.query(ImpactEvent).delete()
        session.query(GraphEdge).delete()
        session.query(GraphNode).delete()
        session.query(ChangeEvent).delete()
        session.commit()


def _seed_change_with_simple_graph() -> int:
    """Create a minimal graph and a ChangeEvent linked to one node.

    Returns the created change_id.
    """

    with Session(engine) as session:
        snapshot_id = 1000

        # Create two nodes A -> B so that downstream impact from A reaches B.
        node_a = GraphNode(object_type="TABLE", object_name="A", snapshot_id=snapshot_id)
        node_b = GraphNode(object_type="TABLE", object_name="B", snapshot_id=snapshot_id)
        session.add_all([node_a, node_b])
        session.flush()

        edge = GraphEdge(
            source_node_id=node_a.node_id,
            target_node_id=node_b.node_id,
            relationship_type="DEPENDS_ON",
            snapshot_id=snapshot_id,
        )
        session.add(edge)

        # Create a ChangeEvent that refers to TABLE A in snapshot_to.
        change = ChangeEvent(
            snapshot_from=snapshot_id - 1,
            snapshot_to=snapshot_id,
            object_type="TABLE",
            object_identifier="A",
            change_type="TABLE_CHANGED",
            before_state=None,
            after_state=None,
        )
        session.add(change)
        session.commit()

        return change.change_id


def _count_impact_events_for_change(change_id: int, snapshot_id: int) -> int:
    with Session(engine) as session:
        return (
            session.query(ImpactEvent)
            .filter(
                ImpactEvent.change_id == change_id,
                ImpactEvent.snapshot_id == snapshot_id,
            )
            .count()
        )


def test_impact_endpoint_happy_path_and_idempotency() -> None:
    _reset_graph_and_impact_state()

    app = _create_test_app()
    client = TestClient(app)

    change_id = _seed_change_with_simple_graph()

    # First execution
    response1 = client.post(f"/api/v1/impact/{change_id}")
    assert response1.status_code == 201

    payload1 = response1.json()
    assert payload1["change_id"] == change_id
    assert "impacts_detected" in payload1
    assert isinstance(payload1["impacts_detected"], int)
    assert payload1["impacts_detected"] >= 0

    impacts_first = payload1["impacts_detected"]

    # Second execution must be idempotent: same count and no duplicates.
    response2 = client.post(f"/api/v1/impact/{change_id}")
    assert response2.status_code == 201
    payload2 = response2.json()

    assert payload2["change_id"] == change_id
    assert payload2["impacts_detected"] == impacts_first


def test_impact_endpoint_returns_404_for_unknown_change_id() -> None:
    _reset_graph_and_impact_state()

    app = _create_test_app()
    client = TestClient(app)

    response = client.post("/api/v1/impact/999999")
    assert response.status_code == 404

    payload = response.json()
    assert "change_id does not exist" in payload["detail"]


def test_impact_endpoint_rejects_non_integer_change_id() -> None:
    _reset_graph_and_impact_state()

    app = _create_test_app()
    client = TestClient(app)

    response = client.post("/api/v1/impact/not-an-int")
    # FastAPI will return 422 for invalid path parameter type.
    assert response.status_code == 422
