from __future__ import annotations

"""Object-search API (v1).

A single, generic autocomplete endpoint for use by every UI component that
needs to let the user pick a database object by name. Replaces ad-hoc
"return all distinct identifiers" endpoints (like the original
``/timeline/objects``) which load tens of thousands of strings into the
browser at once and freeze native ``<select>`` widgets.

Two backing sources are supported via the ``source`` query parameter:

- ``changes`` (default): distinct ``object_identifier`` values from the
  ``change_event`` table. Used when the user is searching among objects
  that have actually changed (e.g. the Timeline page, the TAISA scope
  selector).
- ``graph``: full set of objects in the dependency graph for a given
  snapshot. Used by Simulation / What-If, where every object — even ones
  that never changed — is a valid pick.

The endpoint is built for typeahead UX and never returns more than a
small page (default 20, hard-capped at 100). It exposes ``has_more`` so
the UI can render "Showing 20 of many — keep typing" affordances without
a separate count query (which on large extracts is the slow part).
"""

from typing import List, Literal, Optional

from fastapi import APIRouter, Query, status
from pydantic import BaseModel
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent
from app.graph.graph_models import GraphNode


router = APIRouter(prefix="/objects", tags=["objects"])


class ObjectSearchResponse(BaseModel):
    """Autocomplete page payload.

    ``items`` is the (at most) ``limit`` matching object identifiers,
    sorted alphabetically. ``has_more`` is True when more matches exist
    beyond the page — the UI should prompt the user to refine the query.
    """

    items: List[str]
    has_more: bool
    source: str


@router.get("/search", status_code=status.HTTP_200_OK, response_model=ObjectSearchResponse)
def search_objects(
    q: Optional[str] = Query(
        None,
        description="Substring filter, case-insensitive. Empty/null returns the first `limit` objects.",
    ),
    snapshot_id: Optional[int] = Query(
        None,
        description="Required when `source=graph`; ignored when `source=changes`.",
    ),
    source: Literal["changes", "graph"] = Query(
        "changes",
        description="`changes` = distinct object_identifier from change_event. `graph` = nodes in the snapshot graph.",
    ),
    object_types: Optional[str] = Query(
        None,
        description=(
            "Comma-separated whitelist of `GraphNode.object_type` values "
            "(e.g. `TABLE,VIEW`). Only meaningful with `source=graph`; "
            "ignored on `source=changes` because `change_event.object_type` "
            "uses a different vocabulary (COLUMN / TABLE / SCHEMA / …)."
        ),
    ),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Search for object identifiers matching ``q``.

    Implementation notes
    --------------------
    - We fetch ``limit + 1`` rows on every query and treat the trailing
      one as the ``has_more`` sentinel. This avoids a second ``COUNT(*)``
      round-trip — cheap for autocomplete which doesn't need an exact
      total, just the "are there more?" signal.
    - For ``source=changes`` we use ``DISTINCT`` because the same object
      can appear in many change events; the SQLite query planner serves
      this from the ``object_identifier`` index in microseconds even on
      a 250k-row ``change_event`` table.
    - For ``source=graph`` we synthesise the identifier as
      ``schema_name.object_name`` to match the format the UI uses when
      navigating to other pages. Snapshot is required because the same
      logical object exists once per snapshot.
    """

    pattern = f"%{q.strip()}%" if q and q.strip() else None
    fetch_n = limit + 1  # +1 to detect has_more without a separate COUNT

    with Session(bind=engine) as session:
        if source == "changes":
            stmt = select(distinct(ChangeEvent.object_identifier))
            if pattern is not None:
                stmt = stmt.where(ChangeEvent.object_identifier.ilike(pattern))
            stmt = stmt.order_by(ChangeEvent.object_identifier).limit(fetch_n)
            rows = session.execute(stmt).scalars().all()

        else:  # source == "graph"
            if snapshot_id is None:
                # Empty result rather than a 400 — keeps the UI calling
                # this endpoint defensively (e.g. before a snapshot is
                # picked) cheap and free of error toasts.
                return {"items": [], "has_more": False, "source": source}

            # The graph builder already stores the canonical identifier in
            # `object_name`: qualified "schema.table" for TABLE/VIEW nodes
            # and the bare schema name for SCHEMA nodes. So `object_name`
            # IS the full id — we must NOT prepend `schema_name` again.
            # The old `schema_name + "." + object_name` synthesis produced
            # doubled identifiers like "ACC_TED_VW.ACC_TED_VW.td_ps_ff_..."
            # which only resolved by accident (the focus resolver splits on
            # the first dot) and showed up doubled in the UI. We build the
            # LIKE filter against object_name directly so it still matches
            # the user-visible string.
            from sqlalchemy import func as _func

            full_id = GraphNode.object_name.label("full_id")
            stmt = select(full_id).where(GraphNode.snapshot_id == snapshot_id)
            if pattern is not None:
                stmt = stmt.where(full_id.ilike(pattern))
            # Optional object_type whitelist. The Simulation page uses
            # this to restrict the picker to TABLE / VIEW (the only
            # types its CHANGE_TYPES catalog makes sense against).
            if object_types is not None and object_types.strip():
                wanted = [
                    t.strip().upper()
                    for t in object_types.split(",")
                    if t.strip()
                ]
                if wanted:
                    stmt = stmt.where(GraphNode.object_type.in_(wanted))
            stmt = stmt.order_by(_func.lower(full_id)).limit(fetch_n)
            rows = session.execute(stmt).scalars().all()

    has_more = len(rows) > limit
    items = list(rows[:limit])
    return {"items": items, "has_more": has_more, "source": source}
