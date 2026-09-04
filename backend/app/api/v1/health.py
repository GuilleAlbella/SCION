from __future__ import annotations

"""Health and diagnostics API (v1).

This module defines lightweight health and readiness endpoints for the
backend API.

Responsibilities (future v8.3+):
- Expose basic health checks (e.g. liveness/readiness).
- Optionally surface minimal diagnostics about engine connectivity
  without executing heavy workloads.

Non-responsibilities:
- Running full engine self-tests.
- Performing migrations or schema checks.
- Exposing sensitive operational details.
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import SCION_TAISA_MODE
from app.db.engine import engine
from app.engine_registry import get_engine_states


router = APIRouter(prefix="/health", tags=["health"])


# â"€â"€â"€â"€ Liveness probe: /healthz â"€â"€â"€â"€
# Kubernetes / Docker convention. Must NOT touch the DB or any
# external dependency — its only job is to prove the process is up
# and responsive. If this fails, the orchestrator restarts the pod.
# Anything stateful belongs in /readyz instead.
@router.get(
    "z",  # combined with the prefix `/health` â†’ `/healthz`
    summary="Liveness probe (no dependencies)",
    response_class=JSONResponse,
)
def liveness() -> JSONResponse:
    """Return 200 unconditionally as long as the process is responsive.

    Used by Docker `HEALTHCHECK`, Kubernetes liveness probes, and
    load balancers. Cheap on purpose — no DB query, no engine
    introspection, no external calls. A green `/healthz` means
    "the process is alive"; it does NOT mean "ready to serve
    traffic" (that's `/readyz`).
    """
    return JSONResponse({"status": "ok"}, status_code=status.HTTP_200_OK)


# â"€â"€â"€â"€ Readiness probe: /readyz â"€â"€â"€â"€
# Returns 200 only if the backend can serve real requests. We verify
# DB connectivity with a `SELECT 1` (fast, dialect-agnostic). If the
# DB is unreachable the orchestrator stops sending traffic without
# killing the pod — a transient DB hiccup shouldn't trigger a
# restart cascade.
@router.get(
    "/ready",  # final path: `/api/v1/health/ready`. We keep it under
                # the `/health` prefix instead of a hypothetical
                # standalone `/readyz` because the v1 router has a
                # consistent prefix policy and orchestrators (k8s,
                # Docker) can be configured with any path — the
                # convention is in the response shape, not the URL.
    summary="Readiness probe (DB + engines)",
)
def readiness() -> JSONResponse:
    """Return 200 if the backend can answer real requests, 503 otherwise.

    Checks (in order, fail-fast):
      1. SQLAlchemy can open a connection AND `SELECT 1` returns.
      2. The engine registry reports `database_ready=True`.

    We don't gate on `snapshot_ready` / `diff_ready` / etc. on
    purpose — those engines may be intentionally stopped by an
    operator via the Control panel; that's a degraded state, not
    an unready one.
    """
    db_ok = False
    db_error: str | None = None
    try:
        with Session(engine) as sess:
            sess.execute(text("SELECT 1")).scalar()
            db_ok = True
    except Exception as e:
        db_error = str(e)[:200]  # truncate so the response stays small

    states = get_engine_states()

    payload = {
        "status": "ready" if (db_ok and states["database_ready"]) else "not_ready",
        "checks": {
            "db_select_1": "ok" if db_ok else "error",
            "registry_database_ready": "ok" if states["database_ready"] else "error",
        },
    }
    if db_error:
        payload["db_error"] = db_error

    code = status.HTTP_200_OK if payload["status"] == "ready" else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(payload, status_code=code)


@router.get("", summary="Health check (MVP)")
def health_check() -> dict[str, str]:
    """Report real backend readiness and engine state.

    This endpoint surfaces a lightweight, **truthful** view of the system
    state based on the centralised engine registry:

    - Overall status reflects whether the engine registry has completed
      initialisation.
    - Database readiness is derived from the startup connectivity check.
    - TAISA mode reflects the configured execution mode and whether the
      reasoning client was initialised.
    """

    states = get_engine_states()

    # Overall system status:
    # - "ready"      when all engines are up.
    # - "degraded"   when the registry was initialised but one or more engines
    #                 have been stopped via the control plane.
    # - "initialising" for pre-startup / partially initialised states.

    all_engines_ready = (
        states["database_ready"]
        and states["snapshot_ready"]
        and states["diff_ready"]
        and states["graph_ready"]
        and states["taisa_ready"]
    )

    if states["initialised"] and all_engines_ready:
        status = "ready"
    elif states["initialised"] and not all_engines_ready:
        status = "degraded"
    else:
        status = "initialising"

    # Database readiness uses the outcome of the startup connectivity check.
    database = "ready" if states["database_ready"] else "error"

    # Per-engine readiness derived directly from the registry flags.
    snapshot = "ready" if states["snapshot_ready"] else "stopped"
    diff = "ready" if states["diff_ready"] else "stopped"
    graph = "ready" if states["graph_ready"] else "stopped"

    # TAISA reflects both configuration and initialisation state.
    if SCION_TAISA_MODE == "mock" and states["taisa_ready"]:
        taisa = "mock_ready"
    elif SCION_TAISA_MODE == "real" and states["taisa_ready"]:
        taisa = "real_ready"
    else:
        taisa = "not_ready"

    return {
        "status": status,
        "database": database,
        "snapshot": snapshot,
        "diff": diff,
        "graph": graph,
        "taisa": taisa,
    }
