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

from fastapi import APIRouter

from app.config import SCION_TAISA_MODE
from app.engine_registry import get_engine_states


router = APIRouter(prefix="/health", tags=["health"])


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
