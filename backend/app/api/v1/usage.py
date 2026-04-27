from __future__ import annotations

"""Usage & Criticality API (v1)."""

from typing import Any, Dict, List

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
def get_usage_summary() -> Dict[str, Any]:
    """Return top objects by usage."""

    from sqlalchemy import func, select
    from sqlalchemy.orm import Session
    from app.db.engine import engine
    from app.usage.usage_models import UsageEvent

    with Session(bind=engine) as session:
        rows = session.execute(
            select(
                UsageEvent.object_name,
                UsageEvent.object_type,
                UsageEvent.schema_name,
                func.sum(UsageEvent.query_count).label("total_queries"),
                func.max(UsageEvent.user_count).label("max_users"),
            )
            .group_by(UsageEvent.object_name, UsageEvent.object_type, UsageEvent.schema_name)
            .order_by(func.sum(UsageEvent.query_count).desc())
            .limit(50)
        ).all()

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

    return {"items": items, "total": len(items)}


@router.get(
    "/criticality/{snapshot_id}",
    status_code=status.HTTP_200_OK,
)
def get_criticality(snapshot_id: int, force: bool = False) -> Dict[str, Any]:
    """Compute/retrieve criticality scores for a snapshot."""

    results = compute_criticality(snapshot_id, force=force)
    return {
        "snapshot_id": snapshot_id,
        "items": results,
        "total": len(results),
        "high_count": sum(1 for r in results if r["criticality_level"] == "HIGH"),
        "medium_count": sum(1 for r in results if r["criticality_level"] == "MEDIUM"),
        "low_count": sum(1 for r in results if r["criticality_level"] == "LOW"),
    }
