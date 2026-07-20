"""§2.15 Access Layer — landscape / portfolio-level API endpoints.

GET /landscape/summary
    High-level business view: entity count, high-risk objects,
    recent changes, latest snapshot info.

GET /landscape/risk-overview
    Risk distribution + trending objects + at-risk highlights.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.entity import ObjectEntity
from app.db.models.snapshot import Snapshot
from app.usage.usage_models import ObjectCriticality
from app.diff.diff_models import ChangeEvent

router = APIRouter(prefix="/landscape", tags=["landscape"])


# ── response schemas ─────────────────────────────────────────────────


class RiskObject(BaseModel):
    object_name: str
    schema_name: str
    combined_score: float
    criticality_level: str
    snapshot_id: int


class LandscapeSummary(BaseModel):
    latest_snapshot_id: int | None
    latest_snapshot_time: str | None
    entity_count: int
    active_entity_count: int
    high_risk_count: int
    recent_changes_count: int
    top_risk_objects: list[RiskObject]


class RiskDistribution(BaseModel):
    HIGH: int
    MEDIUM: int
    LOW: int


class LandscapeRiskOverview(BaseModel):
    snapshot_id: int | None
    risk_distribution: RiskDistribution
    top_critical: list[RiskObject]
    recently_changed_high_risk: list[RiskObject]


# ── endpoints ────────────────────────────────────────────────────────


@router.get("/summary", response_model=LandscapeSummary)
def get_landscape_summary(top_n: int = Query(10, le=50)) -> LandscapeSummary:
    """Portfolio-level summary for the business landing page."""
    with Session(bind=engine) as session:
        # Latest snapshot
        latest_snap = session.execute(
            select(Snapshot).order_by(desc(Snapshot.snapshot_id)).limit(1)
        ).scalar_one_or_none()

        snap_id = latest_snap.snapshot_id if latest_snap else None
        snap_time = latest_snap.snapshot_time.isoformat() if latest_snap else None

        # Entity counts
        entity_count = session.execute(select(func.count(ObjectEntity.entity_id))).scalar() or 0
        active_count = (
            session.execute(
                select(func.count(ObjectEntity.entity_id)).where(ObjectEntity.is_active == True)  # noqa: E712
            ).scalar()
            or 0
        )

        # High-risk count (latest snapshot)
        high_risk_count = 0
        if snap_id:
            high_risk_count = (
                session.execute(
                    select(func.count(ObjectCriticality.criticality_id)).where(
                        ObjectCriticality.snapshot_id == snap_id,
                        ObjectCriticality.criticality_level == "HIGH",
                    )
                ).scalar()
                or 0
            )

        # Recent changes (latest snapshot diff)
        recent_changes = 0
        if snap_id:
            recent_changes = (
                session.execute(
                    select(func.count(ChangeEvent.change_id)).where(
                        ChangeEvent.snapshot_to == snap_id
                    )
                ).scalar()
                or 0
            )

        # Top risk objects
        top_rows = []
        if snap_id:
            top_rows = session.execute(
                select(ObjectCriticality)
                .where(ObjectCriticality.snapshot_id == snap_id)
                .order_by(desc(ObjectCriticality.combined_score))
                .limit(top_n)
            ).scalars().all()

        top_risk = [
            RiskObject(
                object_name=r.object_name,
                schema_name=r.object_name.split(".")[0] if "." in r.object_name else "",
                combined_score=round(r.combined_score, 4),
                criticality_level=r.criticality_level,
                snapshot_id=r.snapshot_id,
            )
            for r in top_rows
        ]

        return LandscapeSummary(
            latest_snapshot_id=snap_id,
            latest_snapshot_time=snap_time,
            entity_count=entity_count,
            active_entity_count=active_count,
            high_risk_count=high_risk_count,
            recent_changes_count=recent_changes,
            top_risk_objects=top_risk,
        )


@router.get("/risk-overview", response_model=LandscapeRiskOverview)
def get_risk_overview(
    snapshot_id: int | None = Query(None, description="Default: latest snapshot"),
    top_n: int = Query(10, le=50),
) -> LandscapeRiskOverview:
    """Risk distribution + trending critical objects for the executive view."""
    with Session(bind=engine) as session:
        if snapshot_id is None:
            latest = session.execute(
                select(Snapshot.snapshot_id).order_by(desc(Snapshot.snapshot_id)).limit(1)
            ).scalar_one_or_none()
            snapshot_id = latest

        if snapshot_id is None:
            return LandscapeRiskOverview(
                snapshot_id=None,
                risk_distribution=RiskDistribution(HIGH=0, MEDIUM=0, LOW=0),
                top_critical=[],
                recently_changed_high_risk=[],
            )

        # Distribution
        dist_rows = session.execute(
            select(ObjectCriticality.criticality_level, func.count())
            .where(ObjectCriticality.snapshot_id == snapshot_id)
            .group_by(ObjectCriticality.criticality_level)
        ).all()
        dist = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for level, cnt in dist_rows:
            if level in dist:
                dist[level] = cnt

        # Top critical
        top_rows = session.execute(
            select(ObjectCriticality)
            .where(ObjectCriticality.snapshot_id == snapshot_id)
            .order_by(desc(ObjectCriticality.combined_score))
            .limit(top_n)
        ).scalars().all()

        def _to_risk(r: ObjectCriticality) -> RiskObject:
            return RiskObject(
                object_name=r.object_name,
                schema_name=r.object_name.split(".")[0] if "." in r.object_name else "",
                combined_score=round(r.combined_score, 4),
                criticality_level=r.criticality_level,
                snapshot_id=r.snapshot_id,
            )

        top_critical = [_to_risk(r) for r in top_rows]

        # Recently changed HIGH risk objects
        changed_names = session.execute(
            select(ChangeEvent.object_identifier)
            .where(ChangeEvent.snapshot_to == snapshot_id)
            .distinct()
        ).scalars().all()

        at_risk = session.execute(
            select(ObjectCriticality)
            .where(
                ObjectCriticality.snapshot_id == snapshot_id,
                ObjectCriticality.criticality_level == "HIGH",
                ObjectCriticality.object_name.in_(changed_names),
            )
            .order_by(desc(ObjectCriticality.combined_score))
            .limit(top_n)
        ).scalars().all()

        return LandscapeRiskOverview(
            snapshot_id=snapshot_id,
            risk_distribution=RiskDistribution(**dist),
            top_critical=top_critical,
            recently_changed_high_risk=[_to_risk(r) for r in at_risk],
        )
