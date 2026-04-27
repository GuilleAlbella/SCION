from __future__ import annotations

"""Changes API (v1).

Read-only access to persisted change events detected by the Diff Engine.

Responsibilities:
- Expose a minimal endpoint to list recent changes from the change_event
  table without recomputing diffs.
- Provide enough metadata for the UI to display a meaningful summary and
  select an active change_id.

Non-responsibilities:
- Executing diff logic.
- Executing impact or reasoning.
- Advanced filtering or pagination.
"""

from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent


router = APIRouter(prefix="/changes", tags=["changes"])


class ChangeItem(BaseModel):
    """Minimal representation of a persisted change event for the API."""

    change_id: int
    object_type: str
    object_name: str  # maps to object_identifier in DB
    object_identifier: str
    change_type: str
    snapshot_from: int
    snapshot_to: int
    severity: str | None = None
    is_breaking: bool | None = None
    created_at: datetime


class ChangesResponse(BaseModel):
    """Response payload for the list of recent changes."""

    changes: List[ChangeItem]


@router.get("", status_code=status.HTTP_200_OK, response_model=ChangesResponse)
def list_changes() -> Dict[str, Any]:  # pragma: no cover - thin HTTP wrapper
    """Return the most recent detected changes.

    Behaviour (v10.5):
    - Read from the change_event table only (no diff recomputation).
    - Order by detected_at DESC so newest changes appear first.
    - Limit the result set to a small, reasonable number (e.g. 20).
    - When no changes exist, return {"changes": []}.
    """

    with Session(bind=engine) as session:
        stmt = (
            select(ChangeEvent)
            .order_by(desc(ChangeEvent.detected_at))
            .limit(20)
        )
        rows = session.execute(stmt).scalars().all()

    items: List[Dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "change_id": row.change_id,
                "object_type": row.object_type,
                "object_name": row.object_identifier,
                "object_identifier": row.object_identifier,
                "change_type": row.change_type,
                "snapshot_from": row.snapshot_from,
                "snapshot_to": row.snapshot_to,
                "severity": row.severity,
                "is_breaking": row.is_breaking,
                "created_at": row.detected_at,
            }
        )

    return {"changes": items}
