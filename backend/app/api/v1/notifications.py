from __future__ import annotations

"""Share-folder watcher and notification endpoint.

Scans SCION_SHARE_MOUNT_PATH for new data files and compares their
modification times against the latest snapshot. Returns a notification
when fresher files are present so the frontend can alert the user.
"""

import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SCION_SHARE_MOUNT_PATH
from app.db.engine import engine
from app.db.models.snapshot import Snapshot

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Subdirectory names inside the share → category label
_SHARE_DIRS: dict[str, str] = {
    "Data Dictionary": "dict",
    "Data Lineage":    "lineage",
    "Object Usage":    "pdcr",
    "DBQL":            "dbql",
}

# Pattern to extract YYYYMMDD from filenames like
# pdcr_object_usage_20260607_180000_to_20260608_000000.dat
_DATE_RE = re.compile(r"(\d{8})")


class DataAvailableNotification(BaseModel):
    type: str = "data_available"
    date: str           # YYYY-MM-DD (from filename or mtime)
    files: list[str]    # category labels present in the share
    path: str


class NotificationsResponse(BaseModel):
    notifications: list[DataAvailableNotification]
    share_available: bool
    share_path: str


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _scan_share(mount_path: str) -> tuple[bool, float, list[str], str]:
    """Return (reachable, newest_mtime_epoch, categories, date_label)."""
    base = Path(mount_path)
    if not base.exists():
        return False, 0.0, [], ""

    categories: list[str] = []
    newest_mtime = 0.0
    date_label = ""

    for subdir, category in _SHARE_DIRS.items():
        subpath = base / subdir
        if not subpath.exists():
            continue
        files = [f for f in subpath.iterdir() if f.is_file()]
        if not files:
            continue
        categories.append(category)
        for f in files:
            mt = f.stat().st_mtime
            if mt > newest_mtime:
                newest_mtime = mt
                # Try to extract a readable date from the filename
                m = _DATE_RE.search(f.name)
                if m:
                    raw = m.group(1)
                    date_label = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"

    if not date_label and newest_mtime:
        date_label = datetime.fromtimestamp(newest_mtime).strftime("%Y-%m-%d")

    return True, newest_mtime, categories, date_label


def _latest_snapshot_mtime() -> float:
    """Return the snapshot_time of the most recent snapshot as epoch seconds."""
    with Session(bind=engine) as session:
        row = session.execute(
            select(Snapshot).order_by(Snapshot.snapshot_time.desc()).limit(1)
        ).scalar_one_or_none()
        if row is None:
            return 0.0
        dt: datetime = row.snapshot_time
        # snapshot_time is stored without tzinfo in SQLite — treat as UTC
        return dt.timestamp()


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint
# ──────────────────────────────────────────────────────────────────────────────

@router.get("", response_model=NotificationsResponse)
def get_notifications() -> NotificationsResponse:
    """Return pending data-available notifications for the configured share."""
    mount_path = SCION_SHARE_MOUNT_PATH

    if not mount_path:
        return NotificationsResponse(
            notifications=[], share_available=False, share_path=""
        )

    reachable, newest_mtime, categories, date_label = _scan_share(mount_path)

    if not reachable or not categories:
        return NotificationsResponse(
            notifications=[], share_available=reachable, share_path=mount_path
        )

    latest_mtime = _latest_snapshot_mtime()

    # Only notify when share has files newer than the latest imported snapshot
    if newest_mtime <= latest_mtime:
        return NotificationsResponse(
            notifications=[], share_available=True, share_path=mount_path
        )

    return NotificationsResponse(
        share_available=True,
        share_path=mount_path,
        notifications=[
            DataAvailableNotification(
                date=date_label,
                files=categories,
                path=mount_path,
            )
        ],
    )
