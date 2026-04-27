from __future__ import annotations

"""SCION (Kalido-lite) backend ASGI application entrypoint.

This module wires the FastAPI application for runtime use. It is intentionally
thin and only composes routers and dependencies; all business logic remains in
engines and orchestrators.

Punto 10.2 introduces this entrypoint so that the API can run as a real
long-lived service in local integrated mode, outside of the test runner.

Punto 10.2.b extends this by performing eager, centralised initialisation of
all core engines during application startup. If any engine fails to
initialise, the exception is propagated and the application fails to start,
ensuring deterministic readiness.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import v1_router
from app.engine_registry import get_engine_states, initialise_engines


app = FastAPI(title="SCION API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "SCION API",
        "version": "1.0.0",
        "health": "/api/v1/health",
    }


@app.on_event("startup")
def startup_event() -> None:
    """Initialise all SCION engines eagerly at application startup.

    Any error during initialisation will abort the startup sequence. Logs
    emitted by :func:`initialise_engines` describe the sequence.
    """

    initialise_engines()

    # Print a concise, demo-friendly summary of engine readiness so that
    # console output on startup clearly shows which SCION engines are running.
    states = get_engine_states()

    metadata_status = "ready" if states["database_ready"] else "error"
    snapshot_status = "ready" if states["snapshot_ready"] else "stopped"
    diff_status = "ready" if states["diff_ready"] else "stopped"
    graph_status = "ready" if states["graph_ready"] else "stopped"
    taisa_status = "ready" if states["taisa_ready"] else "stopped"

    print("[SCION] Engine startup status:")
    print(f"  - Metadata API: {metadata_status}")
    print(f"  - Snapshot Engine: {snapshot_status}")
    print(f"  - Diff Engine: {diff_status}")
    print(f"  - Impact / Graph Engine: {graph_status}")
    print(f"  - TAISA Reasoning: {taisa_status}")


# Attach versioned API router under the canonical prefix.
app.include_router(v1_router)
