from __future__ import annotations

"""Timeline API (v1).

Returns the change history for a specific object across all snapshots.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
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
    """Paginated timeline payload.

    ``events`` is the current page; ``total`` is the count of all events
    matching the object filter (across pages). ``has_more`` lets the UI
    decide whether to render a "load more" affordance.
    """

    object_identifier: str
    events: List[TimelineEvent]
    total: int
    limit: int
    offset: int
    has_more: bool


# Server-side defaults / hard caps for timeline pagination. Default is
# generous (200) because the typical use case — a single object's history —
# rarely has more than a few dozen events; the cap exists for the pathological
# case where ``object_name`` is short enough that the substring match catches
# tens of thousands of identifiers.
TIMELINE_LIMIT_DEFAULT = 200
TIMELINE_LIMIT_MAX = 1000


@router.get("", status_code=status.HTTP_200_OK, response_model=TimelineResponse)
def get_timeline(
    object_name: str = Query(..., description="Object identifier to search"),
    limit: int = Query(TIMELINE_LIMIT_DEFAULT, ge=1, le=TIMELINE_LIMIT_MAX),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Get a paginated change history for a specific object.

    Filter is unchanged from the pre-pagination revision: exact match OR
    substring match on ``object_identifier``, so the user can search by
    short name ("accounts") or fully-qualified ("core_banking.accounts").
    The query is now ``LIMIT``-bounded and a separate ``COUNT(*)`` runs
    against the same filter to populate ``total`` for the UI.
    """

    # Build snapshot time lookup once. Snapshot count is small (dozens),
    # so loading them all is cheap and lets us O(1)-attach the timestamp
    # to every event row below.
    with Session(bind=engine) as session:
        snapshots = session.execute(select(Snapshot)).scalars().all()
        snap_times = {
            s.snapshot_id: s.snapshot_time.isoformat() if s.snapshot_time else ""
            for s in snapshots
        }

    # Shared filter — applied to both COUNT and the page query. Pre-built
    # once so the two queries can't drift if the filter logic changes.
    where_clause = or_(
        ChangeEvent.object_identifier.ilike(object_name),
        ChangeEvent.object_identifier.ilike(f"%{object_name}%"),
    )

    with Session(bind=engine) as session:
        # Total count (for UI "Showing X of Y" + has_more).
        total = int(
            session.execute(
                select(func.count()).select_from(ChangeEvent).where(where_clause)
            ).scalar_one()
            or 0
        )

        rows = session.execute(
            select(ChangeEvent)
            .where(where_clause)
            .order_by(ChangeEvent.snapshot_to, ChangeEvent.detected_at)
            .offset(offset)
            .limit(limit)
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

    has_more = (offset + len(events)) < total

    return {
        "object_identifier": object_name,
        "events": events,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
    }


class TimelineObjectsResponse(BaseModel):
    objects: List[str]


@router.get("/objects", status_code=status.HTTP_200_OK, response_model=TimelineObjectsResponse)
def list_timeline_objects() -> Dict[str, Any]:
    """List unique object identifiers that have changes.

    DEPRECATED in v1.15: this endpoint loads up to ``TIMELINE_OBJECTS_HARD_CAP``
    distinct identifiers in one shot, which on Rahul's Transcend extract
    (~240k distinct identifiers) freezes the browser's native ``<select>``.
    New UI code should use ``GET /objects/search?q=...`` instead. We keep
    this endpoint working for any external script that still calls it, but
    capped so it can't bring the server down.
    """
    TIMELINE_OBJECTS_HARD_CAP = 1000
    with Session(bind=engine) as session:
        rows = session.execute(
            select(ChangeEvent.object_identifier)
            .distinct()
            .order_by(ChangeEvent.object_identifier)
            .limit(TIMELINE_OBJECTS_HARD_CAP)
        ).scalars().all()

    return {"objects": list(rows)}
