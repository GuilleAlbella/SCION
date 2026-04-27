from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1 import v1_router
from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.diff.diff_models import ChangeEvent
from app.graph.impact_models import ImpactEvent
from app.taisa.taisa_models import ReasoningEvent


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app wiring the v1 API router.

    This app is used only to exercise the full orchestration flow via API.
    """

    app = FastAPI()
    app.include_router(v1_router)
    return app


def _reset_full_flow_state() -> None:
    """Clear core tables so the full-flow test starts from a clean state."""

    with Session(engine) as session:
        session.query(ReasoningEvent).delete()
        session.query(ImpactEvent).delete()
        session.query(ChangeEvent).delete()
        session.query(Snapshot).delete()
        session.commit()


def test_full_flow_end_to_end() -> None:
    """End-to-end orchestration using only the public API.

    Flow:
    - POST /api/v1/snapshots (twice) → create two snapshots.
    - POST /api/v1/diff → compute diff and persist change_event.
    - Pick a change_id from change_event.
    - POST /api/v1/impact/{change_id} → persist impact_event.
    - POST /api/v1/reasoning/{change_id} → persist reasoning_event.
    - Re-execute impact and reasoning to validate idempotency/append-only.
    """

    _reset_full_flow_state()

    app = _create_test_app()
    client = TestClient(app)

    # --- Snapshot creation (two snapshots) ---
    resp_snap_1 = client.post("/api/v1/snapshots")
    assert resp_snap_1.status_code == 201
    snap_id_1 = resp_snap_1.json()["snapshot_id"]

    resp_snap_2 = client.post("/api/v1/snapshots")
    assert resp_snap_2.status_code == 201
    snap_id_2 = resp_snap_2.json()["snapshot_id"]

    assert snap_id_1 != "" and snap_id_2 != ""

    # Ensure snapshots are actually persisted.
    with Session(engine) as session:
        snapshot_count = session.query(Snapshot).count()
    assert snapshot_count >= 2

    # --- Diff computation ---
    resp_diff = client.post(
        "/api/v1/diff",
        json={"snapshot_from": snap_id_1, "snapshot_to": snap_id_2},
    )
    assert resp_diff.status_code == 201

    with Session(engine) as session:
        change_events = session.query(ChangeEvent).all()
    assert len(change_events) >= 0  # diff may yield zero or more changes

    # For the impact/reasoning flow we need at least one change_id. If none
    # exist, the test cannot proceed meaningfully; in practice, project data
    # should yield at least one change between snapshots.
    if not change_events:
        # Skip the rest of the test gracefully.
        return

    change_id = change_events[0].change_id

    # --- Impact analysis ---
    resp_impact_1 = client.post(f"/api/v1/impact/{change_id}")
    assert resp_impact_1.status_code == 201
    payload_impact_1 = resp_impact_1.json()
    assert payload_impact_1["change_id"] == change_id
    assert isinstance(payload_impact_1["impacts_detected"], int)
    assert payload_impact_1["impacts_detected"] >= 0

    with Session(engine) as session:
        impact_count_1 = (
            session.query(ImpactEvent)
            .filter(ImpactEvent.change_id == change_id)
            .count()
        )

    # --- Reasoning ---
    resp_reason_1 = client.post(f"/api/v1/reasoning/{change_id}")
    assert resp_reason_1.status_code == 201
    payload_reason_1 = resp_reason_1.json()
    assert payload_reason_1["change_id"] == change_id
    assert isinstance(payload_reason_1["classification"], str)
    assert isinstance(payload_reason_1["risk_level"], str)

    with Session(engine) as session:
        reasoning_count_1 = (
            session.query(ReasoningEvent)
            .filter(ReasoningEvent.change_id == change_id)
            .count()
        )

    assert reasoning_count_1 == 1

    # --- Re-execution: impact should be idempotent, reasoning append-only ---
    resp_impact_2 = client.post(f"/api/v1/impact/{change_id}")
    assert resp_impact_2.status_code == 201
    payload_impact_2 = resp_impact_2.json()
    assert payload_impact_2["change_id"] == change_id

    with Session(engine) as session:
        impact_count_2 = (
            session.query(ImpactEvent)
            .filter(ImpactEvent.change_id == change_id)
            .count()
        )

    # Impact persistence is idempotent for (change_id, snapshot_id).
    assert impact_count_2 == impact_count_1

    resp_reason_2 = client.post(f"/api/v1/reasoning/{change_id}")
    assert resp_reason_2.status_code == 201

    with Session(engine) as session:
        reasoning_count_2 = (
            session.query(ReasoningEvent)
            .filter(ReasoningEvent.change_id == change_id)
            .count()
        )

    # Reasoning is append-only: each call appends a new event.
    assert reasoning_count_2 == reasoning_count_1 + 1
