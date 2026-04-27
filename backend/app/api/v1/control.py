from __future__ import annotations

"""Control-plane API (v1).

This module exposes lightweight, *logical* control operations for SCION
engines. It allows stopping and restarting individual engines within the
running backend process without shutting down the whole service.

Scope (v10.5.b):
- Stop/restart flags and instances in the engine registry.
- No OS-level process management.
- No new business capabilities.

These endpoints are intended to be called from the UI control plane and are
protected by the standard API key dependency via router composition.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.engine_registry import restart_engine, stop_engine


router = APIRouter(prefix="/control", tags=["control"])


class EngineControlResponse(BaseModel):
    """Response payload for engine control operations."""

    engine: str
    action: str
    status: str


@router.post(
    "/stop/{engine_name}",
    status_code=status.HTTP_200_OK,
    response_model=EngineControlResponse,
    summary="Logically stop an engine",
)
def stop_engine_endpoint(engine_name: str) -> EngineControlResponse:
    """Mark the given engine as stopped in the registry.

    This does not terminate the FastAPI/uvicorn process; it only prevents
    further use of the selected engine until it is restarted.
    """

    try:
        stop_engine(engine_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return EngineControlResponse(engine=engine_name, action="stop", status="ok")


@router.post(
    "/restart/{engine_name}",
    status_code=status.HTTP_200_OK,
    response_model=EngineControlResponse,
    summary="Restart an engine in-place",
)
def restart_engine_endpoint(engine_name: str) -> EngineControlResponse:
    """Recreate the selected engine instance and mark it as ready again."""

    try:
        restart_engine(engine_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return EngineControlResponse(engine=engine_name, action="restart", status="ok")
