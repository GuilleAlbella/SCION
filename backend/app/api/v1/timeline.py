from __future__ import annotations

"""Timeline API (v1).

Returns the change history for a specific object across all snapshots.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent
from app.db.models.snapshot import Snapshot


router = APIRouter(prefix="/timeline", tags=["timeline"])


class TimelineEvent(BaseModel):
    change_id: int
    snapshot_from: int
    snapshot_to: int
    snapshot_time: str
    change_type: str
    severity: str
    is_breaking: bool
    before_state: Dict[str, Any] | None = None
    after_state: Dict[str, Any] | None = None


class TimelineResponse(BaseModel):
    object_identifier: str
    events: List[TimelineEvent]
    total: int


@router.get("", status_code=status.HTTP_200_OK, response_model=TimelineResponse)
def get_timeline(object_name: str = Query(..., description="Object identifier to search")) -> Dict[str, Any]:
    """Get the full change history for a specific object."""

    # Build snapshot time lookup
    with Session(bind=engine) as session:
        snapshots = session.execute(select(Snapshot)).scalars().all()
        snap_times = {s.snapshot_id: s.snapshot_time.isoformat() if s.snapshot_time else "" for s in snapshots}

    # "contains" match is intentional — lets the user query by short table
    # name (e.g. "accounts") and still catch fully-qualified identifiers
    # ("core_banking.accounts"). Exact match is tried via the OR so single-
    # segment object names still work without wildcarding surprises.
    with Session(bind=engine) as session:
        rows = session.execute(
            select(ChangeEvent)
            .where(
                or_(
                    ChangeEvent.object_identifier == object_name,
                    ChangeEvent.object_identifier.contains(object_name),
                )
            )
            .order_by(ChangeEvent.snapshot_to, ChangeEvent.detected_at)
        ).scalars().all()

    events = []
    for r in rows:
        events.append({
            "change_id": r.change_id,
            "snapshot_from": r.snapshot_from,
            "snapshot_to": r.snapshot_to,
            "snapshot_time": snap_times.get(r.snapshot_to, ""),
            "change_type": r.change_type,
            "severity": r.severity or "LOW",
            "is_breaking": r.is_breaking or False,
            "before_state": r.before_state,
            "after_state": r.after_state,
        })

    return {
        "object_identifier": object_name,
        "events": events,
        "total": len(events),
    }


class TimelineObjectsResponse(BaseModel):
    objects: List[str]


@router.get("/objects", status_code=status.HTTP_200_OK, response_model=TimelineObjectsResponse)
def list_timeline_objects() -> Dict[str, Any]:
    """List all unique object identifiers that have changes."""
    with Session(bind=engine) as session:
        rows = session.execute(
            select(ChangeEvent.object_identifier).distinct()
        ).scalars().all()

    return {"objects": sorted(rows)}
