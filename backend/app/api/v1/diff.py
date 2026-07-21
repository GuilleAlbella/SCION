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

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, case, func, or_, select
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
    with Session(engine) as session:
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
    """Aggregate counts over the FULL filtered set, not just the page.

    These drive the KPI cards on the Changes page; they must reflect the
    total impact of the diff (e.g. "12,500 breaking changes") regardless
    of which page is currently being viewed.
    """

    total: int
    breaking_count: int
    high_count: int
    medium_count: int
    low_count: int


class DiffDetailResponse(BaseModel):
    """Paginated change-events payload.

    ``changes`` is a single page (sized by ``limit``). ``summary`` is
    computed over every change matching the same filters, so the UI
    can render aggregate KPIs without having to walk all pages.
    """

    snapshot_from: int
    snapshot_to: int
    summary: DiffDetailSummary
    changes: List[DiffDetailItem]
    limit: int
    offset: int
    has_more: bool


# Server-side defaults / hard caps for diff-details pagination. ``LIMIT_MAX``
# is the ceiling we'll enforce regardless of what the client sends â€” large
# enough that scripts and ad-hoc API consumers can pull a useful chunk in
# one round trip, small enough that no single response can OOM the browser
# or the server's response buffer on a 250k-change extract.
DIFF_DETAILS_LIMIT_DEFAULT = 100
DIFF_DETAILS_LIMIT_MAX = 1000


@router.get(
    "/{snapshot_from}/{snapshot_to}/details",
    status_code=status.HTTP_200_OK,
    response_model=DiffDetailResponse,
)
def get_diff_details(
    snapshot_from: int,
    snapshot_to: int,
    limit: int = Query(DIFF_DETAILS_LIMIT_DEFAULT, ge=1, le=DIFF_DETAILS_LIMIT_MAX),
    offset: int = Query(0, ge=0),
    severity: Optional[str] = Query(
        None,
        description="HIGH / MEDIUM / LOW. Omit (or pass 'ALL') to skip filtering.",
    ),
    is_breaking: Optional[bool] = Query(
        None,
        description="When set, restrict to breaking (true) or non-breaking (false) changes.",
    ),
    object_q: Optional[str] = Query(
        None,
        description="Case-insensitive substring filter against object_identifier.",
    ),
) -> Dict[str, Any]:
    """Return one paginated page of change events between two snapshots.

    History
    -------
    Pre-paginated revisions returned every change event in a single
    response, plus an in-Python summary computed by counting rows. With
    Rahul's Transcend extract that meant ~250k rows + tens of MB of
    JSON in one response â€” the browser couldn't survive parsing it.

    The endpoint now:

    1. Resolves the snapshot range into a list of consecutive pairs (the
       cumulative-pairs strategy is unchanged: 1â†’3 is computed as
       1â†’2 âˆª 2â†’3, so non-adjacent jumps still work).
    2. Auto-materialises any missing pair via ``compute_diff`` *only on
       the first page* (offset == 0). Subsequent page fetches assume the
       pair is already persisted; they don't redo the work.
    3. Builds a single ``WHERE`` clause covering all pairs + the optional
       severity/breaking/object filters and uses it twice:
       (a) for a small ``GROUP BY severity, is_breaking`` summary count,
       (b) for the page itself with ``ORDER BY ... LIMIT ... OFFSET``.
    4. Returns at most ``limit`` rows plus a ``has_more`` flag so the UI
       can decide whether to render a "load more" affordance.

    Filter semantics
    ----------------
    - ``severity``: case-insensitive; "ALL" or null disables the filter.
    - ``is_breaking``: tri-state â€” null means "any", true/false restrict.
    - ``object_q``: ``ILIKE %q%`` against ``object_identifier``.
    """

    # â”€â”€â”€â”€ Direction normalisation â”€â”€â”€â”€
    # Always work with the lower snapshot_id as "from" so the pair filter
    # matches the canonical rows stored by DiffEngine (which normalises the
    # same way). The cumulative-pairs range query also requires from <= to.
    if snapshot_from > snapshot_to:
        snapshot_from, snapshot_to = snapshot_to, snapshot_from

    # â”€â”€â”€â”€ Step 1: resolve snapshots into consecutive pairs â”€â”€â”€â”€
    with Session(db_engine) as session:
        all_snaps = session.execute(
            select(Snapshot.snapshot_id)
            .where(
                Snapshot.snapshot_id >= snapshot_from,
                Snapshot.snapshot_id <= snapshot_to,
            )
            .order_by(Snapshot.snapshot_id)
        ).scalars().all()

    pairs: List[tuple] = []
    if len(all_snaps) >= 2:
        for i in range(len(all_snaps) - 1):
            pairs.append((all_snaps[i], all_snaps[i + 1]))
    else:
        pairs = [(snapshot_from, snapshot_to)]

    # â”€â”€â”€â”€ Step 2: idempotent compute_diff (first page only) â”€â”€â”€â”€
    # Doing this on every page would be wasteful and would make pagination
    # weirdly slow on offset>0 fetches. compute_diff is itself idempotent
    # (it short-circuits when the pair already has change_event rows), so
    # gating on offset==0 just avoids the redundant call.
    if offset == 0:
        try:
            diff_engine = get_diff_engine()
            for sf, st in pairs:
                if sf != st:
                    diff_engine.compute_diff(sf, st)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Diff computation failed for range %d->%d: %s",
                snapshot_from,
                snapshot_to,
                exc,
            )

    # â”€â”€â”€â”€ Step 3: build the shared filter expression â”€â”€â”€â”€
    # We previously used `tuple_(...).in_(pairs)` to push the pair filter
    # in one shot, but SQLite's planner doesn't always recognise row-value
    # IN as eligible for index seeks on a composite-key index â€” depending
    # on version it falls back to a full table scan. Expanding to a plain
    # OR-of-equality-pairs gives the planner unambiguous index hints,
    # which on tables with a hot `change_event` (250k+ rows) is the
    # difference between sub-100 ms and seconds.
    pair_filter = or_(
        *[
            and_(
                ChangeEvent.snapshot_from == sf,
                ChangeEvent.snapshot_to == st,
            )
            for sf, st in pairs
        ]
    )
    filters = [pair_filter]

    if severity is not None and severity.strip() and severity.strip().upper() != "ALL":
        filters.append(ChangeEvent.severity == severity.strip().upper())
    if is_breaking is not None:
        filters.append(ChangeEvent.is_breaking == is_breaking)
    if object_q is not None and object_q.strip():
        filters.append(
            ChangeEvent.object_identifier.ilike(f"%{object_q.strip()}%")
        )

    where_clause = and_(*filters)

    # â”€â”€â”€â”€ Steps 4 & 5: summary + page â”€â”€â”€â”€
    # One session covers both queries so we don't pay the connection-acquire
    # / PRAGMA-emission cost twice. Summary (small GROUP BY) and page
    # (LIMIT/OFFSET) read the same rows, so SQLite's page cache warms up
    # for the second query when they share a connection.
    with Session(db_engine) as session:
        summary_rows = session.execute(
            select(
                ChangeEvent.severity,
                ChangeEvent.is_breaking,
                func.count().label("n"),
            )
            .where(where_clause)
            .group_by(ChangeEvent.severity, ChangeEvent.is_breaking)
        ).all()

        page_rows = session.execute(
            select(ChangeEvent)
            .where(where_clause)
            .order_by(
                ChangeEvent.is_breaking.desc(),
                case(
                    (ChangeEvent.severity == "HIGH", 1),
                    (ChangeEvent.severity == "MEDIUM", 2),
                    else_=3,
                ),
                ChangeEvent.change_id,
            )
            .offset(offset)
            .limit(limit)
        ).scalars().all()

    total = 0
    breaking_count = 0
    high_count = 0
    medium_count = 0
    low_count = 0
    for sev, brk, n in summary_rows:
        n = int(n or 0)
        total += n
        if brk:
            breaking_count += n
        sev_norm = (sev or "LOW").upper()
        if sev_norm == "HIGH":
            high_count += n
        elif sev_norm == "MEDIUM":
            medium_count += n
        else:
            low_count += n

    changes = []
    for row in page_rows:
        changes.append({
            "change_id": row.change_id,
            "object_type": row.object_type,
            "object_identifier": row.object_identifier,
            "change_type": row.change_type,
            "severity": row.severity or "LOW",
            "is_breaking": row.is_breaking or False,
            "before_state": row.before_state,
            "after_state": row.after_state,
            "snapshot_from": row.snapshot_from,
            "snapshot_to": row.snapshot_to,
            "detected_at": row.detected_at.isoformat() if row.detected_at else "",
        })

    has_more = (offset + len(changes)) < total

    return {
        "snapshot_from": snapshot_from,
        "snapshot_to": snapshot_to,
        "summary": {
            "total": total,
            "breaking_count": breaking_count,
            "high_count": high_count,
            "medium_count": medium_count,
            "low_count": low_count,
        },
        "changes": changes,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
    }
