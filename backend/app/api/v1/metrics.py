from __future__ import annotations

"""Metrics API (v1).

Structural metrics: object counts, growth rate, volatility, structural hash.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel

from app.snapshot.snapshot_metrics import (
    compute_snapshot_metrics,
    compute_growth_rate,
    compute_volatility_index,
)
from app.snapshot.structural_hash import compute_structural_hash


router = APIRouter(prefix="/metrics", tags=["metrics"])


class SnapshotMetricsResponse(BaseModel):
    snapshot_id: int
    schema_count: int
    table_count: int
    view_count: int
    column_count: int
    total_objects: int
    structural_hash: Optional[str]


class GrowthResponse(BaseModel):
    snapshot_from: int
    snapshot_to: int
    objects_added: int
    objects_removed: int
    net_change: int
    growth_percentage: float
    schemas_added: int
    schemas_removed: int
    tables_added: int
    tables_removed: int


class VolatilityResponse(BaseModel):
    volatility_index: float
    snapshot_count: int


@router.get(
    "/snapshot/{snapshot_id}",
    status_code=status.HTTP_200_OK,
    response_model=SnapshotMetricsResponse,
)
def get_snapshot_metrics(
    snapshot_id: int,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """Object counts and structural hash for a single snapshot.

    Reads the persisted ``Snapshot.structural_hash`` from the DB
    rather than recomputing it. The hash is calculated once at
    ingest time (see ``snapshot_finaliser``) and stored — recomputing
    on every call streams ~9.8M rows for a Transcend-class snapshot
    and was the cause of the /metrics page hanging when one big
    snapshot was loaded alongside the demo set: the frontend fetches
    metrics for every snapshot in series, so one ~30s recompute
    blocked all the skeletons behind it.

    For legacy snapshots (NULL hash), we return null immediately and
    kick off the recompute in the background so the next call is fast.
    """

    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.db.engine import engine
    from app.db.models.snapshot import Snapshot

    metrics = compute_snapshot_metrics(snapshot_id)

    with Session(engine) as session:
        sha = session.scalar(
            select(Snapshot.structural_hash).where(
                Snapshot.snapshot_id == snapshot_id
            )
        )

    # Lazy backfill: legacy snapshots ingested before the column was
    # populated will have NULL here. Kick off the recompute in the
    # background so this request returns immediately — the next call
    # will find the hash already persisted.
    if not sha:
        def _backfill(sid: int) -> None:
            h = compute_structural_hash(sid)
            with Session(engine) as s:
                row = s.get(Snapshot, sid)
                if row is not None:
                    row.structural_hash = h
                    s.commit()

        background_tasks.add_task(_backfill, snapshot_id)

    return {
        **metrics.to_dict(),
        "structural_hash": sha,
    }


@router.get(
    "/growth",
    status_code=status.HTTP_200_OK,
    response_model=GrowthResponse,
)
def get_growth_rate(
    snapshot_from: int = Query(..., alias="from"),
    snapshot_to: int = Query(..., alias="to"),
) -> Dict[str, Any]:
    """Growth rate between two snapshots."""

    growth = compute_growth_rate(snapshot_from, snapshot_to)
    return growth.to_dict()


@router.get(
    "/volatility",
    status_code=status.HTTP_200_OK,
    response_model=VolatilityResponse,
)
def get_volatility() -> Dict[str, Any]:
    """Volatility index across all snapshots."""

    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.db.engine import engine
    from app.db.models.snapshot import Snapshot

    with Session(engine) as session:
        ids = list(session.scalars(
            select(Snapshot.snapshot_id).order_by(Snapshot.snapshot_time)
        ).all())

    vol = compute_volatility_index(ids)
    return {
        "volatility_index": vol,
        "snapshot_count": len(ids),
    }
