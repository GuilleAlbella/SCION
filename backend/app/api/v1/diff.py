from __future__ import annotations

"""Diff API (v1).

This module defines the API surface for diff-related operations in version 1
of the backend API.

Responsibilities (future v8.3+):
- Orchestrate calls to the Diff Engine.
- Expose endpoints to compute and inspect change events.
- Provide traceability by `snapshot_id` and `change_id`.

Non-responsibilities:
- Implementing diff/compare algorithms.
- Mutating database state directly.
- Any UI or presentation logic.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine_registry import get_diff_engine
from app.db.engine import engine as db_engine
from app.db.models.snapshot import Snapshot
from app.diff.diff_models import ChangeEvent


router = APIRouter(prefix="/diff", tags=["diff"])


class DiffRequest(BaseModel):
    """Request payload for executing a diff between two snapshots.

    The API accepts snapshot identifiers as strings to remain agnostic to the
    underlying ID format. For the current implementation, these are expected
    to be stringified integer primary keys produced by the snapshot layer.
    """

    snapshot_from: str
    snapshot_to: str


class DiffResponse(BaseModel):
    """Minimal diff execution summary returned by the API."""

    snapshot_from: str
    snapshot_to: str
    changes_detected: int


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DiffResponse)
def execute_diff(request: DiffRequest) -> DiffResponse:
    """Execute the Diff Engine for a pair of snapshots and persist changes.

    Behaviour (MVP v8.3.3):

    - Validates that both snapshots exist and are different.
    - Delegates diff computation and `change_event` persistence to the
      existing `DiffEngine`.
    - Returns a minimal summary with the number of detected/persisted changes.

    The endpoint is stateless and does not touch Graph, Impact, or TAISA
    components.
    """

    # Resolve external snapshot identifiers (strings) to internal integer IDs.
    try:
        snapshot_from_id = int(request.snapshot_from)
        snapshot_to_id = int(request.snapshot_to)
    except ValueError as exc:  # pragma: no cover - defensive path
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid snapshot identifiers; expected numeric values.",
        ) from exc

    if snapshot_from_id == snapshot_to_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="snapshot_from and snapshot_to must be different.",
        )

    # Local imports to avoid exposing engine or ORM symbols at module level.
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.engine import engine
    from app.db.models.snapshot import Snapshot

    # Validate that both snapshots exist before invoking the engine.
    with Session(bind=engine) as session:
        stmt_from = select(Snapshot.snapshot_id).where(
            Snapshot.snapshot_id == snapshot_from_id
        )
        stmt_to = select(Snapshot.snapshot_id).where(
            Snapshot.snapshot_id == snapshot_to_id
        )

        exists_from = session.execute(stmt_from).scalar_one_or_none()
        exists_to = session.execute(stmt_to).scalar_one_or_none()

    if exists_from is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="snapshot_from does not exist.",
        )

    if exists_to is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="snapshot_to does not exist.",
        )

    # Execute diff using the shared, eagerly initialised engine from the
    # registry. This avoids per-request construction and aligns with the
    # centralised engine lifecycle.
    try:
        diff_engine = get_diff_engine()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    changes = diff_engine.compute_diff(snapshot_from_id, snapshot_to_id)

    return DiffResponse(
        snapshot_from=request.snapshot_from,
        snapshot_to=request.snapshot_to,
        changes_detected=len(changes),
    )


class DiffDetailItem(BaseModel):
    change_id: int
    object_type: str
    object_identifier: str
    change_type: str
    severity: Optional[str] = None
    is_breaking: Optional[bool] = None
    before_state: Optional[Dict[str, Any]] = None
    after_state: Optional[Dict[str, Any]] = None
    snapshot_from: int
    snapshot_to: int
    detected_at: str


class DiffDetailSummary(BaseModel):
    total: int
    breaking_count: int
    high_count: int
    medium_count: int
    low_count: int


class DiffDetailResponse(BaseModel):
    snapshot_from: int
    snapshot_to: int
    summary: DiffDetailSummary
    changes: List[DiffDetailItem]


@router.get(
    "/{snapshot_from}/{snapshot_to}/details",
    status_code=status.HTTP_200_OK,
    response_model=DiffDetailResponse,
)
def get_diff_details(snapshot_from: int, snapshot_to: int) -> Dict[str, Any]:
    """Return all change events between two snapshots.

    If the snapshots are not consecutive, accumulates changes across all
    intermediate pairs (e.g. 1→3 returns changes from 1→2 + 2→3).
    """

    from app.db.models.snapshot import Snapshot

    # ──── Cumulative-pairs strategy ────
    # If the user requests 1→3 but diffs were only computed for consecutive
    # pairs (1→2 and 2→3), we walk every intermediate snapshot and union
    # their change events. This guarantees the answer stays consistent even
    # when the user jumps across non-adjacent snapshots.
    with Session(bind=db_engine) as session:
        all_snaps = session.execute(
            select(Snapshot.snapshot_id)
            .where(
                Snapshot.snapshot_id >= snapshot_from,
                Snapshot.snapshot_id <= snapshot_to,
            )
            .order_by(Snapshot.snapshot_id)
        ).scalars().all()

    # Build all consecutive pairs that sit inside the requested range.
    pairs = []
    if len(all_snaps) >= 2:
        for i in range(len(all_snaps) - 1):
            pairs.append((all_snaps[i], all_snaps[i + 1]))
    else:
        # Fallback — nothing in between, treat as a direct pair.
        pairs = [(snapshot_from, snapshot_to)]

    # Idempotent safety net: re-running compute_diff on an already-computed
    # pair is a no-op, but this ensures any missing pair is materialised
    # before we read the change_event rows below.
    try:
        diff_engine = get_diff_engine()
        for sf, st in pairs:
            if sf != st:
                diff_engine.compute_diff(sf, st)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Diff computation failed for range %d->%d: %s", snapshot_from, snapshot_to, exc)

    # Load all change events across all pairs
    with Session(bind=db_engine) as session:
        rows = []
        for sf, st in pairs:
            pair_rows = (
                session.query(ChangeEvent)
                .filter(
                    ChangeEvent.snapshot_from == sf,
                    ChangeEvent.snapshot_to == st,
                )
                .all()
            )
            rows.extend(pair_rows)
        # Sort by snapshot pair then by change_id for consistent ordering
        rows.sort(key=lambda r: (r.snapshot_from, r.snapshot_to, r.change_id))

    changes = []
    breaking_count = 0
    high_count = 0
    medium_count = 0
    low_count = 0

    for row in rows:
        sev = row.severity or "LOW"
        brk = row.is_breaking or False
        if brk:
            breaking_count += 1
        if sev == "HIGH":
            high_count += 1
        elif sev == "MEDIUM":
            medium_count += 1
        else:
            low_count += 1

        changes.append({
            "change_id": row.change_id,
            "object_type": row.object_type,
            "object_identifier": row.object_identifier,
            "change_type": row.change_type,
            "severity": sev,
            "is_breaking": brk,
            "before_state": row.before_state,
            "after_state": row.after_state,
            "snapshot_from": row.snapshot_from,
            "snapshot_to": row.snapshot_to,
            "detected_at": row.detected_at.isoformat() if row.detected_at else "",
        })

    return {
        "snapshot_from": snapshot_from,
        "snapshot_to": snapshot_to,
        "summary": {
            "total": len(changes),
            "breaking_count": breaking_count,
            "high_count": high_count,
            "medium_count": medium_count,
            "low_count": low_count,
        },
        "changes": changes,
    }
