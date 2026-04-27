from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import v1_router


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app wiring the v1 API router.

    This app is used only to exercise the diff and snapshot endpoints. It does
    not register extra middleware or dependencies beyond the versioned router.
    """

    app = FastAPI()
    app.include_router(v1_router)
    return app


def _create_snapshot(client: TestClient) -> str:
    """Helper to create a snapshot via the API and return its ID as string."""

    response = client.post("/api/v1/snapshots")
    assert response.status_code == 201

    payload = response.json()
    snapshot_id = payload["snapshot_id"]
    assert isinstance(snapshot_id, str)
    assert snapshot_id != ""
    return snapshot_id


def test_diff_endpoint_happy_path() -> None:
    app = _create_test_app()
    client = TestClient(app)

    # Arrange: create two snapshots via the API so they exist in the DB.
    snapshot_from = _create_snapshot(client)
    snapshot_to = _create_snapshot(client)

    # Act
    response = client.post(
        "/api/v1/diff",
        json={
            "snapshot_from": snapshot_from,
            "snapshot_to": snapshot_to,
        },
    )

    # Assert
    assert response.status_code == 201

    payload = response.json()
    assert payload["snapshot_from"] == snapshot_from
    assert payload["snapshot_to"] == snapshot_to
    assert "changes_detected" in payload
    assert isinstance(payload["changes_detected"], int)
    assert payload["changes_detected"] >= 0


def test_diff_endpoint_rejects_same_snapshot_ids() -> None:
    app = _create_test_app()
    client = TestClient(app)

    snapshot_id = _create_snapshot(client)

    response = client.post(
        "/api/v1/diff",
        json={
            "snapshot_from": snapshot_id,
            "snapshot_to": snapshot_id,
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert "snapshot_from and snapshot_to must be different" in payload["detail"]


def test_diff_endpoint_rejects_nonexistent_snapshot_from() -> None:
    app = _create_test_app()
    client = TestClient(app)

    # Create only the target snapshot so that snapshot_from is missing.
    snapshot_to = _create_snapshot(client)

    response = client.post(
        "/api/v1/diff",
        json={
            "snapshot_from": "9999999",  # unlikely to exist in the test DB
            "snapshot_to": snapshot_to,
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert "snapshot_from does not exist" in payload["detail"]


def test_diff_endpoint_rejects_nonexistent_snapshot_to() -> None:
    app = _create_test_app()
    client = TestClient(app)

    snapshot_from = _create_snapshot(client)

    response = client.post(
        "/api/v1/diff",
        json={
            "snapshot_from": snapshot_from,
            "snapshot_to": "9999999",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert "snapshot_to does not exist" in payload["detail"]


def test_diff_endpoint_requires_body_fields() -> None:
    app = _create_test_app()
    client = TestClient(app)

    # Missing snapshot_to should result in a validation error (422 from FastAPI).
    snapshot_from = _create_snapshot(client)

    response = client.post(
        "/api/v1/diff",
        json={"snapshot_from": snapshot_from},
    )

    assert response.status_code == 422
