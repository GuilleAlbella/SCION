from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import v1_router


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app wiring the v1 API router.

    This app is used only for exercising the snapshots endpoints. It does not
    add extra middleware or custom dependencies; it simply mounts the
    versioned router under its configured prefix ("/api/v1").
    """

    app = FastAPI()
    app.include_router(v1_router)
    return app


def test_create_snapshot_endpoint_returns_snapshot_id() -> None:
    app = _create_test_app()
    client = TestClient(app)

    response = client.post("/api/v1/snapshots")

    assert response.status_code == 201

    payload = response.json()
    assert isinstance(payload, dict)
    assert "snapshot_id" in payload
    assert isinstance(payload["snapshot_id"], str)
    assert payload["snapshot_id"] != ""


def test_list_snapshots_endpoint_returns_list() -> None:
    app = _create_test_app()
    client = TestClient(app)

    # First call: there may or may not be existing snapshots. The endpoint
    # must still respond with HTTP 200 and a list.
    response = client.get("/api/v1/snapshots")
    assert response.status_code == 200

    payload = response.json()
    assert isinstance(payload, dict)
    assert "snapshots" in payload
    assert isinstance(payload["snapshots"], list)

    # Create at least one snapshot to ensure the listing can contain entries
    # without relying on external test ordering.
    create_response = client.post("/api/v1/snapshots")
    assert create_response.status_code == 201

    list_response = client.get("/api/v1/snapshots")
    assert list_response.status_code == 200

    list_payload = list_response.json()
    assert isinstance(list_payload, dict)
    assert "snapshots" in list_payload
    assert isinstance(list_payload["snapshots"], list)

    # When snapshots exist, each entry must expose at least snapshot_id and
    # created_at, and snapshot_id must be non-empty.
    for item in list_payload["snapshots"]:
        assert "snapshot_id" in item
        assert "created_at" in item
        assert isinstance(item["snapshot_id"], str)
        assert item["snapshot_id"] != ""
