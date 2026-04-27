from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import v1_router


def _create_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(v1_router)
    return app


def test_endpoints_work_without_api_key_configured(monkeypatch) -> None:
    """When API_KEY is not set, security is disabled and all endpoints work.

    This keeps the existing tests and local/dev usage unchanged.
    """

    # Ensure API_KEY is not set.
    monkeypatch.delenv("API_KEY", raising=False)

    app = _create_test_app()
    client = TestClient(app)

    # Health should always work.
    resp_health = client.get("/api/v1/health")
    assert resp_health.status_code == 200

    # Protected endpoints should also work when security is disabled.
    resp_snap = client.post("/api/v1/snapshots")
    assert resp_snap.status_code == 201


def test_protected_endpoints_require_api_key_when_configured(monkeypatch) -> None:
    """When API_KEY is set, protected endpoints enforce X-API-Key.

    Health remains public for liveness checks.
    """

    api_key = "test-secret-key"
    monkeypatch.setenv("API_KEY", api_key)

    app = _create_test_app()
    client = TestClient(app)

    # Health is public: no API key required.
    resp_health = client.get("/api/v1/health")
    assert resp_health.status_code == 200

    # Missing key on protected endpoint → 401.
    resp_missing = client.post("/api/v1/snapshots")
    assert resp_missing.status_code == 401
    assert "Missing X-API-Key" in resp_missing.json()["detail"]

    # Wrong key → 403.
    resp_wrong = client.post("/api/v1/snapshots", headers={"X-API-Key": "wrong"})
    assert resp_wrong.status_code == 403
    assert "Invalid API key" in resp_wrong.json()["detail"]

    # Correct key → 201 and normal behaviour.
    resp_ok = client.post("/api/v1/snapshots", headers={"X-API-Key": api_key})
    assert resp_ok.status_code == 201
