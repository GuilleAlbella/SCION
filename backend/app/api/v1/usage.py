from __future__ import annotations

"""Usage & Criticality API (v1)."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.usage.usage_ingestor import ingest_usage_json
from app.usage.criticality_engine import compute_criticality


router = APIRouter(prefix="/usage", tags=["usage"])


class IngestResponse(BaseModel):
    ingested: int


class UsageSummaryItem(BaseModel):
    object_name: str
    object_type: str | None = None
    schema_name: str | None = None
    query_count: int
    user_count: int


class CriticalityItem(BaseModel):
    object_name: str
    usage_score: float
    graph_score: float
    combined_score: float
    criticality_level: str


@router.post("/ingest", status_code=status.HTTP_201_CREATED, response_model=IngestResponse)
def ingest_usage(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ingest usage data from external parser JSON."""
    count = ingest_usage_json(data)
    return {"ingested": count}


@router.get("/summary", status_code=status.HTTP_200_OK)
def get_usage_summary(snapshot_id: Optional[int] = None) -> Dict[str, Any]:
    """Return top objects by usage.

    `UsageEvent` rows are not tied to a `snapshot_id` (the table was
    designed as a "global" usage observation feed before the per-snapshot
    model was firmed up). To make this endpoint snapshot-scoped without
    a schema migration, we filter the aggregation by joining usage rows
    against the snapshot's `graph_node` set on `object_name`. Result:

    - With `snapshot_id`: only objects that exist in that snapshot's
      graph are returned. A snapshot whose objects have no matching
      usage_event rows (e.g. dict-imported snapshots, since dict
      doesn't bring usage data) returns an empty list.
    - Without `snapshot_id`: legacy behaviour — global aggregation
      across every usage_event row.

    Why a graph_node join (and not table_snapshot): graph_node has the
    fully-qualified `object_name` (`schema.table`) which is what
    UsageEvent.object_name uses too. Joining on table_snapshot would
    require concatenating `schema_name + '.' + table_name` per row;
    cheaper to use the materialised graph names.
    """

    from sqlalchemy import func, select
    from sqlalchemy.orm import Session
    from app.db.engine import engine
    from app.usage.usage_models import UsageEvent
    from app.graph.graph_models import GraphNode

    with Session(bind=engine) as session:
        stmt = (
            select(
                UsageEvent.object_name,
                UsageEvent.object_type,
                UsageEvent.schema_name,
                func.sum(UsageEvent.query_count).label("total_queries"),
                func.max(UsageEvent.user_count).label("max_users"),
            )
            .group_by(UsageEvent.object_name, UsageEvent.object_type, UsageEvent.schema_name)
            .order_by(func.sum(UsageEvent.query_count).desc())
        )

        if snapshot_id is not None:
            # Restrict to objects present in the snapshot's graph.
            # `IN (subquery)` is fine here — graph_node is small per
            # snapshot (hundreds to thousands of rows even for big
            # warehouses) and SQLite/Postgres both pick a hash join.
            scoped_names = (
                select(GraphNode.object_name)
                .where(GraphNode.snapshot_id == snapshot_id)
            )
            stmt = stmt.where(UsageEvent.object_name.in_(scoped_names))

        # Hard cap is 50 rows post-filter — keeps the payload small
        # for the UI which only ever shows the top 12 in the heatmap.
        stmt = stmt.limit(50)
        rows = session.execute(stmt).all()

    items = [
        {
            "object_name": r.object_name,
            "object_type": r.object_type,
            "schema_name": r.schema_name,
            "query_count": r.total_queries or 0,
            "user_count": r.max_users or 0,
        }
        for r in rows
    ]

    return {"items": items, "total": len(items), "snapshot_id": snapshot_id}


@router.get("/object/{snapshot_id}", status_code=status.HTTP_200_OK)
def get_object_usage_detail(snapshot_id: int, object: str) -> Dict[str, Any]:
    """Full usage + criticality profile for ONE object in a snapshot.

    Powers the Usage page's per-object drill-down — click a row, or arrive
    via ``/usage?object=X`` from a Changes row. Unlike ``/summary`` and
    ``/criticality`` (which return top-N rankings), this resolves a
    specific object even when it sits far outside the top of either list,
    so the drill-down works for any object the user navigates to.

    Name resolution. ``object_criticality`` stores the qualified
    ``schema.object`` identifier (it's built from ``graph_node``), while
    ``usage_event`` stores the bare object name plus a separate
    ``schema_name`` (PDCR layout). We match both encodings and, when the
    caller passes a qualified name, disambiguate the bare match by schema
    so we don't sum a same-named table from another database.
    """
    from sqlalchemy import and_, func, or_, select
    from sqlalchemy.orm import Session
    from app.db.engine import engine
    from app.usage.usage_models import ObjectCriticality, UsageEvent

    qualified = object
    leaf = object.split(".")[-1]
    schema = object.split(".")[0] if "." in object else None

    with Session(bind=engine) as session:
        # Case-insensitive match: PDCR emits identifiers in UPPERCASE while
        # the dictionary preserves the CREATE-statement case, so an exact
        # compare would miss most real usage rows (the same reason the
        # PDCR persister resolves case-insensitively against graph_node).
        usage_filter = or_(
            func.lower(UsageEvent.object_name) == qualified.lower(),
            and_(
                func.lower(UsageEvent.object_name) == leaf.lower(),
                or_(
                    schema is None,
                    func.lower(UsageEvent.schema_name) == schema.lower(),
                ),
            ),
        )
        total_queries, max_users, last_accessed, usage_obj_type = session.execute(
            select(
                func.sum(UsageEvent.query_count),
                func.max(UsageEvent.user_count),
                func.max(UsageEvent.last_accessed),
                func.max(UsageEvent.object_type),
            ).where(usage_filter)
        ).one()

        crit = (
            session.execute(
                select(ObjectCriticality).where(
                    ObjectCriticality.snapshot_id == snapshot_id,
                    ObjectCriticality.object_name == qualified,
                )
            )
            .scalars()
            .first()
        )

    has_usage = total_queries is not None
    return {
        "snapshot_id": snapshot_id,
        "object": qualified,
        "found": bool(has_usage or crit),
        "object_type": usage_obj_type,
        "schema_name": schema,
        "usage": {
            "query_count": int(total_queries or 0),
            "user_count": int(max_users or 0),
            "last_accessed": last_accessed.isoformat() if last_accessed else None,
            "has_data": has_usage,
        },
        "criticality": (
            {
                "usage_score": crit.usage_score,
                "graph_score": crit.graph_score,
                "combined_score": crit.combined_score,
                "criticality_level": crit.criticality_level,
            }
            if crit
            else None
        ),
    }


@router.get(
    "/criticality/{snapshot_id}",
    status_code=status.HTTP_200_OK,
)
def get_criticality(
    snapshot_id: int,
    force: bool = False,
    limit: int = 100,
) -> Dict[str, Any]:
    """Compute/retrieve criticality scores for a snapshot.

    Behaviour (v1.19+)
    ------------------
    The page only renders the top-N most-critical objects (KPI cards
    + heatmap), so streaming all 337k rows of a Transcend extract is
    pointless and freezes the browser on JSON parse. We return:

    - ``items``: top ``limit`` objects sorted by ``combined_score``
      desc. The ``ix_object_criticality_snapshot_score`` composite
      index added in v1.15.00 makes this an indexed range scan even
      on Transcend-scale data.
    - ``total`` / ``high_count`` / ``medium_count`` / ``low_count``:
      counts over the FULL set, computed via a single ``GROUP BY``
      so we don't have to scan all rows to get them.

    Force / cache-miss path: when no rows exist for the snapshot OR
    ``force=True`` is set, we delegate to ``compute_criticality`` and
    let it run the full pipeline. New imports always go through the
    post-ingest hook (which calls ``compute_criticality(force=True,
    usage_available=False)``) so the cache should be hit on every
    user-driven request.
    """

    capped_limit = max(1, min(limit, 500))

    from sqlalchemy import case, func, select
    from sqlalchemy.orm import Session
    from app.db.engine import engine
    from app.usage.usage_models import ObjectCriticality

    if not force:
        # Cheap pre-flight: does the cache exist for this snapshot?
        with Session(engine) as session:
            cached_count = int(
                session.execute(
                    select(func.count())
                    .select_from(ObjectCriticality)
                    .where(ObjectCriticality.snapshot_id == snapshot_id)
                ).scalar_one()
                or 0
            )

        if cached_count > 0:
            with Session(engine) as session:
                # Single GROUP BY to populate all four counts in one
                # round-trip — at most 3 buckets returned regardless of
                # how many rows the snapshot contains.
                level_rows = session.execute(
                    select(
                        ObjectCriticality.criticality_level,
                        func.count().label("n"),
                    )
                    .where(ObjectCriticality.snapshot_id == snapshot_id)
                    .group_by(ObjectCriticality.criticality_level)
                ).all()

                # Top-N items via indexed scan; never materialises more
                # than ``capped_limit`` rows in Python.
                top_rows = session.execute(
                    select(ObjectCriticality)
                    .where(ObjectCriticality.snapshot_id == snapshot_id)
                    .order_by(ObjectCriticality.combined_score.desc())
                    .limit(capped_limit)
                ).scalars().all()

            counts = {lvl: int(n or 0) for lvl, n in level_rows}
            return {
                "snapshot_id": snapshot_id,
                "items": [
                    {
                        "object_name": r.object_name,
                        "usage_score": r.usage_score,
                        "graph_score": r.graph_score,
                        "combined_score": r.combined_score,
                        "criticality_level": r.criticality_level,
                    }
                    for r in top_rows
                ],
                "total": cached_count,
                "high_count": counts.get("HIGH", 0),
                "medium_count": counts.get("MEDIUM", 0),
                "low_count": counts.get("LOW", 0),
            }

    # Cache miss or forced — fall back to the full compute path. This
    # is potentially expensive on Transcend-scale snapshots; future
    # work could move it to a background task with progress reporting,
    # but in the v1.19 flow post-ingest always populates the cache so
    # this branch only fires for legacy data.
    results = compute_criticality(snapshot_id, force=force)
    return {
        "snapshot_id": snapshot_id,
        "items": results[:capped_limit],
        "total": len(results),
        "high_count": sum(1 for r in results if r["criticality_level"] == "HIGH"),
        "medium_count": sum(1 for r in results if r["criticality_level"] == "MEDIUM"),
        "low_count": sum(1 for r in results if r["criticality_level"] == "LOW"),
    }
