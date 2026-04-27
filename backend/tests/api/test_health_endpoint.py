from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import v1_router


def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app for exercising the v1 API router.

    This app is used only in tests for the health endpoint. It wires in the
    versioned router under its own prefix and does not add any extra
    middleware, dependencies, or engine integrations.
    """

    app = FastAPI()
    app.include_router(v1_router)
    return app


def test_health_endpoint_exists_and_returns_ok() -> None:
    app = _create_test_app()
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200

    payload = response.json()
    assert isinstance(payload, dict)

    assert payload["status"] == "ok"
    assert "database" in payload
    assert "taisa" in payload
