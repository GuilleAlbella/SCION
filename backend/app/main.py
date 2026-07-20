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

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import v1_router
from app.engine_registry import get_engine_states, initialise_engines
from app.logging_config import configure_logging

# Configure logging before any other app code runs so that engine
# initialisation logs are captured in the right format from the start.
configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):  # noqa: ARG001
    """FastAPI lifespan — startup + shutdown hook.

    Replaces the deprecated @app.on_event("startup") pattern. Engines are
    initialised here so FastAPI's dependency injection is fully wired by the
    time the first request arrives.
    """
    initialise_engines()

    states = get_engine_states()
    logger.info(
        "SCION engine startup complete",
        extra={
            "metadata":  "ready" if states["database_ready"] else "error",
            "snapshot":  "ready" if states["snapshot_ready"] else "stopped",
            "diff":      "ready" if states["diff_ready"]     else "stopped",
            "graph":     "ready" if states["graph_ready"]    else "stopped",
            "taisa":     "ready" if states["taisa_ready"]    else "stopped",
        },
    )

    yield  # application runs here

    logger.info("SCION shutdown")


app = FastAPI(title="SCION API", version="1.0.0", lifespan=lifespan)

_origins_raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
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


# Attach versioned API router under the canonical prefix.
app.include_router(v1_router)
