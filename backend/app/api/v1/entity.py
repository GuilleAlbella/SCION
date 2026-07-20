"""§2.9 Integration Model — entity API endpoints.

GET /entity/resolve?name=SCHEMA.TABLE&type=TABLE
    Look up a persistent entity by natural key.

GET /entity/{entity_id}
    Get entity metadata.

GET /entity/{entity_id}/history
    Full criticality + usage + change history across snapshots.

GET /entity/
    List active entities (paginated, filterable by schema / type).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.entity import ObjectEntity
from app.db.models.snapshot import Snapshot
from app.usage.usage_models import ObjectCriticality, UsageEvent
from app.diff.diff_models import ChangeEvent

router = APIRouter(prefix="/entity", tags=["entity"])


# ── response schemas ─────────────────────────────────────────────────


class EntityResponse(BaseModel):
    entity_id: int
    entity_type: str
    schema_name: str
    object_name: str
    first_seen_snapshot_id: int
    last_seen_snapshot_id: int
    is_active: bool
    created_at: str

    class Config:
        from_attributes = True


class CriticalityPoint(BaseModel):
    snapshot_id: int
    snapshot_time: str
    combined_score: float
    criticality_level: str
    usage_score: float
    graph_score: float


class UsagePoint(BaseModel):
    snapshot_id: int
    snapshot_time: str
    query_count: int
    user_count: int


class EntityHistoryResponse(BaseModel):
    entity_id: int
    object_name: str
    entity_type: str
    criticality_history: list[CriticalityPoint]
    usage_history: list[UsagePoint]
    change_count: int
    snapshots_seen: int


class EntityListResponse(BaseModel):
    entities: list[EntityResponse]
    total: int
    has_more: bool


# ── helpers ──────────────────────────────────────────────────────────


def _get_entity_or_404(entity_id: int, session: Session) -> ObjectEntity:
    entity = session.get(ObjectEntity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
    return entity


# ── endpoints ────────────────────────────────────────────────────────


@router.get("/resolve", response_model=EntityResponse)
def resolve_entity(
    name: str = Query(..., description="Fully-qualified object name, e.g. SCHEMA.TABLE"),
    type: str = Query("TABLE", description="Entity type: TABLE | VIEW | SCHEMA | COLUMN"),
) -> EntityResponse:
    """Look up a persistent entity by its natural key (type + FQ name)."""
    with Session(bind=engine) as session:
        entity = session.execute(
            select(ObjectEntity).where(
                ObjectEntity.entity_type == type.upper(),
                ObjectEntity.object_name == name.upper(),
            )
        ).scalar_one_or_none()

        if entity is None:
            # Try case-insensitive fallback
            entity = session.execute(
                select(ObjectEntity).where(
                    func.upper(ObjectEntity.entity_type) == type.upper(),
                    func.upper(ObjectEntity.object_name) == name.upper(),
                )
            ).scalar_one_or_none()

        if entity is None:
            raise HTTPException(
                status_code=404,
                detail=f"Entity '{name}' (type={type}) not found",
            )
        return EntityResponse(
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            schema_name=entity.schema_name,
            object_name=entity.object_name,
            first_seen_snapshot_id=entity.first_seen_snapshot_id,
            last_seen_snapshot_id=entity.last_seen_snapshot_id,
            is_active=entity.is_active,
            created_at=entity.created_at.isoformat(),
        )


@router.get("/{entity_id}", response_model=EntityResponse)
def get_entity(entity_id: int) -> EntityResponse:
    with Session(bind=engine) as session:
        entity = _get_entity_or_404(entity_id, session)
        return EntityResponse(
            entity_id=entity.entity_id,
            entity_type=entity.entity_type,
            schema_name=entity.schema_name,
            object_name=entity.object_name,
            first_seen_snapshot_id=entity.first_seen_snapshot_id,
            last_seen_snapshot_id=entity.last_seen_snapshot_id,
            is_active=entity.is_active,
            created_at=entity.created_at.isoformat(),
        )


@router.get("/{entity_id}/history", response_model=EntityHistoryResponse)
def get_entity_history(entity_id: int) -> EntityHistoryResponse:
    """Return full criticality + usage + change history across snapshots for an entity."""
    with Session(bind=engine) as session:
        entity = _get_entity_or_404(entity_id, session)

        # Criticality history — join snapshot for timestamps
        crit_rows = session.execute(
            select(
                ObjectCriticality.snapshot_id,
                Snapshot.snapshot_time,
                ObjectCriticality.combined_score,
                ObjectCriticality.criticality_level,
                ObjectCriticality.usage_score,
                ObjectCriticality.graph_score,
            )
            .join(Snapshot, ObjectCriticality.snapshot_id == Snapshot.snapshot_id)
            .where(ObjectCriticality.object_name == entity.object_name)
            .order_by(Snapshot.snapshot_time)
        ).all()

        criticality_history = [
            CriticalityPoint(
                snapshot_id=r.snapshot_id,
                snapshot_time=r.snapshot_time.isoformat(),
                combined_score=round(r.combined_score, 4),
                criticality_level=r.criticality_level,
                usage_score=round(r.usage_score, 4),
                graph_score=round(r.graph_score, 4),
            )
            for r in crit_rows
        ]

        # Usage history
        usage_rows = session.execute(
            select(
                UsageEvent.snapshot_id,
                Snapshot.snapshot_time,
                UsageEvent.query_count,
                UsageEvent.user_count,
            )
            .join(Snapshot, UsageEvent.snapshot_id == Snapshot.snapshot_id)
            .where(UsageEvent.entity_id == entity_id)
            .order_by(Snapshot.snapshot_time)
        ).all()

        usage_history = [
            UsagePoint(
                snapshot_id=r.snapshot_id,
                snapshot_time=r.snapshot_time.isoformat(),
                query_count=r.query_count,
                user_count=r.user_count,
            )
            for r in usage_rows
        ]

        # Change count
        change_count = session.execute(
            select(func.count()).where(ChangeEvent.entity_id == entity_id)
        ).scalar() or 0

        # Snapshot count (distinct snapshots where this object was seen)
        seen_count = len(
            set(r.snapshot_id for r in crit_rows)
            | set(r.snapshot_id for r in usage_rows)
        )

        return EntityHistoryResponse(
            entity_id=entity_id,
            object_name=entity.object_name,
            entity_type=entity.entity_type,
            criticality_history=criticality_history,
            usage_history=usage_history,
            change_count=change_count,
            snapshots_seen=seen_count,
        )


@router.get("/", response_model=EntityListResponse)
def list_entities(
    schema: Optional[str] = Query(None, description="Filter by schema name"),
    type: Optional[str] = Query(None, description="Filter by entity type"),
    active_only: bool = Query(True),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
) -> EntityListResponse:
    with Session(bind=engine) as session:
        q = select(ObjectEntity)
        if active_only:
            q = q.where(ObjectEntity.is_active == True)  # noqa: E712
        if schema:
            q = q.where(ObjectEntity.schema_name == schema)
        if type:
            q = q.where(ObjectEntity.entity_type == type.upper())

        total = session.execute(
            select(func.count()).select_from(q.subquery())
        ).scalar() or 0

        entities = session.execute(
            q.order_by(ObjectEntity.object_name).offset(offset).limit(limit)
        ).scalars().all()

        return EntityListResponse(
            entities=[
                EntityResponse(
                    entity_id=e.entity_id,
                    entity_type=e.entity_type,
                    schema_name=e.schema_name,
                    object_name=e.object_name,
                    first_seen_snapshot_id=e.first_seen_snapshot_id,
                    last_seen_snapshot_id=e.last_seen_snapshot_id,
                    is_active=e.is_active,
                    created_at=e.created_at.isoformat(),
                )
                for e in entities
            ],
            total=total,
            has_more=(offset + limit) < total,
        )
