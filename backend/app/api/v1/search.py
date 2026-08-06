from __future__ import annotations

"""Global Search API (v1).

Searches across graph nodes, change events, and snapshots for matching objects.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Query, status
from pydantic import BaseModel
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.graph.graph_models import GraphNode
from app.diff.diff_models import ChangeEvent


router = APIRouter(prefix="/search", tags=["search"])


class SearchResult(BaseModel):
    object_name: str
    object_type: str
    schema_name: str
    snapshot_id: int
    context: str


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
    total: int


@router.get("", status_code=status.HTTP_200_OK, response_model=SearchResponse)
def global_search(q: str = Query(..., min_length=1, description="Search query")) -> Dict[str, Any]:
    """Search for objects by name across graph nodes and change events."""

    # Dedup via composite key: the same object may appear as both a graph
    # node and a change event — we want a single result row per "thing".
    results: List[Dict[str, Any]] = []
    seen = set()
    query_lower = q.lower()

    # Search graph nodes
    with Session(bind=engine) as session:
        nodes = session.execute(
            select(GraphNode).where(
                or_(
                    GraphNode.object_name.ilike(f"%{q}%"),
                    GraphNode.schema_name.ilike(f"%{q}%"),
                )
            )
            .limit(50)
        ).scalars().all()

        for n in nodes:
            key = f"{(n.schema_name or '').lower()}.{n.object_name.lower()}:{n.snapshot_id}"
            if key not in seen:
                seen.add(key)
                results.append({
                    "object_name": n.object_name,
                    "object_type": n.object_type,
                    "schema_name": n.schema_name or "",
                    "snapshot_id": n.snapshot_id,
                    "context": f"Graph node in snapshot #{n.snapshot_id}",
                })

    # Search change events
    with Session(bind=engine) as session:
        changes = session.execute(
            select(ChangeEvent).where(
                ChangeEvent.object_identifier.ilike(f"%{q}%")
            )
            .limit(50)
        ).scalars().all()

        for c in changes:
            key = f"change:{c.object_identifier}:{c.change_id}"
            if key not in seen:
                seen.add(key)
                parts = c.object_identifier.split(".")
                results.append({
                    "object_name": c.object_identifier,
                    "object_type": c.object_type,
                    "schema_name": parts[0] if parts else "",
                    "snapshot_id": c.snapshot_to,
                    "context": f"{c.change_type} (#{c.snapshot_from}→#{c.snapshot_to})",
                })

    # Relevance tiering: exact match (0) > prefix match (1) > contains (2).
    # Python's sort is stable, so within a tier results keep their DB order.
    def relevance(r: Dict[str, Any]) -> int:
        name = r["object_name"].lower()
        if name == query_lower:
            return 0
        if name.startswith(query_lower):
            return 1
        return 2

    results.sort(key=relevance)

    return {
        "query": q,
        "results": results[:30],
        "total": len(results),
    }
