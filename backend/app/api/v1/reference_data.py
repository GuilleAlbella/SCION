"""§2.10 Reference Data — query endpoints.

GET /reference/teams           — org hierarchy (teams + department)
GET /reference/applications    — business applications with mapping counts
GET /reference/usage-by-team   — usage stats grouped by team/department
GET /reference/usage-by-app    — usage stats grouped by application
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.reference import (
    ApplicationEntity,
    DatabaseApplicationMapping,
    DepartmentEntity,
    TableApplicationMapping,
    TeamEntity,
    UserEntity,
)
from app.db.models.snapshot import Snapshot
from app.usage.usage_models import UsageEvent

router = APIRouter(prefix="/reference", tags=["reference"])


# ── response schemas ──────────────────────────────────────────────────


class TeamRow(BaseModel):
    team_id: int
    team_name: str
    department_name: str | None
    user_count: int


class TeamsResponse(BaseModel):
    teams: list[TeamRow]
    total: int


class AppRow(BaseModel):
    application_id: int
    application_name: str
    description: str | None
    owner_team: str | None
    schema_count: int
    table_count: int


class ApplicationsResponse(BaseModel):
    applications: list[AppRow]
    total: int


class TeamUsageRow(BaseModel):
    team_name: str
    department_name: str | None
    query_count: int
    user_count: int
    object_count: int


class TeamUsageResponse(BaseModel):
    snapshot_id: int | None
    teams: list[TeamUsageRow]
    unmapped_query_count: int
    note: str | None


class AppUsageRow(BaseModel):
    application_name: str
    schema_count: int
    table_count: int
    query_count: int
    user_count: int


class AppUsageResponse(BaseModel):
    snapshot_id: int | None
    applications: list[AppUsageRow]
    unmapped_query_count: int


# ── endpoints ─────────────────────────────────────────────────────────


@router.get("/teams", response_model=TeamsResponse)
def get_teams() -> TeamsResponse:
    """List all teams with department name and user count."""
    with Session(bind=engine) as session:
        rows = (
            session.execute(
                select(
                    TeamEntity.team_id,
                    TeamEntity.team_name,
                    DepartmentEntity.department_name,
                    func.count(UserEntity.user_id).label("user_count"),
                )
                .outerjoin(DepartmentEntity, TeamEntity.department_id == DepartmentEntity.department_id)
                .outerjoin(UserEntity, UserEntity.team_id == TeamEntity.team_id)
                .group_by(
                    TeamEntity.team_id,
                    TeamEntity.team_name,
                    DepartmentEntity.department_name,
                )
                .order_by(DepartmentEntity.department_name, TeamEntity.team_name)
            )
            .all()
        )
        teams = [
            TeamRow(
                team_id=r.team_id,
                team_name=r.team_name,
                department_name=r.department_name,
                user_count=r.user_count,
            )
            for r in rows
        ]
        return TeamsResponse(teams=teams, total=len(teams))


@router.get("/applications", response_model=ApplicationsResponse)
def get_applications() -> ApplicationsResponse:
    """List all applications with owner team and mapping counts."""
    with Session(bind=engine) as session:
        rows = (
            session.execute(
                select(
                    ApplicationEntity.application_id,
                    ApplicationEntity.application_name,
                    ApplicationEntity.description,
                    TeamEntity.team_name.label("owner_team"),
                    func.count(DatabaseApplicationMapping.mapping_id.distinct()).label("schema_count"),
                    func.count(TableApplicationMapping.mapping_id.distinct()).label("table_count"),
                )
                .outerjoin(TeamEntity, ApplicationEntity.owner_team_id == TeamEntity.team_id)
                .outerjoin(
                    DatabaseApplicationMapping,
                    DatabaseApplicationMapping.application_id == ApplicationEntity.application_id,
                )
                .outerjoin(
                    TableApplicationMapping,
                    TableApplicationMapping.application_id == ApplicationEntity.application_id,
                )
                .group_by(
                    ApplicationEntity.application_id,
                    ApplicationEntity.application_name,
                    ApplicationEntity.description,
                    TeamEntity.team_name,
                )
                .order_by(ApplicationEntity.application_name)
            )
            .all()
        )
        apps = [
            AppRow(
                application_id=r.application_id,
                application_name=r.application_name,
                description=r.description,
                owner_team=r.owner_team,
                schema_count=r.schema_count,
                table_count=r.table_count,
            )
            for r in rows
        ]
        return ApplicationsResponse(applications=apps, total=len(apps))


@router.get("/usage-by-team", response_model=TeamUsageResponse)
def get_usage_by_team(
    snapshot_id: int | None = Query(None, description="Default: latest snapshot"),
) -> TeamUsageResponse:
    """Usage statistics grouped by team.

    Requires PDCR extractor to provide per-user rows (username column).
    Returns empty teams list with a note when username data is absent.
    """
    with Session(bind=engine) as session:
        if snapshot_id is None:
            snapshot_id = session.execute(
                select(Snapshot.snapshot_id).order_by(desc(Snapshot.snapshot_id)).limit(1)
            ).scalar_one_or_none()

        if snapshot_id is None:
            return TeamUsageResponse(
                snapshot_id=None, teams=[], unmapped_query_count=0, note=None
            )

        # Check if any username data exists for this snapshot
        has_usernames = (
            session.execute(
                select(func.count(UsageEvent.usage_id)).where(
                    UsageEvent.snapshot_id == snapshot_id,
                    UsageEvent.username.isnot(None),
                )
            ).scalar()
            or 0
        ) > 0

        if not has_usernames:
            total_qc = (
                session.execute(
                    select(func.sum(UsageEvent.query_count)).where(
                        UsageEvent.snapshot_id == snapshot_id
                    )
                ).scalar()
                or 0
            )
            return TeamUsageResponse(
                snapshot_id=snapshot_id,
                teams=[],
                unmapped_query_count=total_qc,
                note=(
                    "No per-user data available yet. The PDCR extractor must provide "
                    "username per row to enable team-level breakdowns."
                ),
            )

        # Join usage_event → user_entity → team_entity → department_entity
        rows = session.execute(
            select(
                TeamEntity.team_name,
                DepartmentEntity.department_name,
                func.sum(UsageEvent.query_count).label("query_count"),
                func.count(UsageEvent.usage_id.distinct()).label("user_count"),
                func.count(UsageEvent.object_name.distinct()).label("object_count"),
            )
            .join(UserEntity, UsageEvent.username == UserEntity.username)
            .join(TeamEntity, UserEntity.team_id == TeamEntity.team_id)
            .outerjoin(DepartmentEntity, TeamEntity.department_id == DepartmentEntity.department_id)
            .where(UsageEvent.snapshot_id == snapshot_id)
            .group_by(TeamEntity.team_name, DepartmentEntity.department_name)
            .order_by(desc("query_count"))
        ).all()

        mapped_qc = sum(r.query_count or 0 for r in rows)
        total_qc = (
            session.execute(
                select(func.sum(UsageEvent.query_count)).where(
                    UsageEvent.snapshot_id == snapshot_id
                )
            ).scalar()
            or 0
        )

        teams = [
            TeamUsageRow(
                team_name=r.team_name,
                department_name=r.department_name,
                query_count=r.query_count or 0,
                user_count=r.user_count,
                object_count=r.object_count,
            )
            for r in rows
        ]

        return TeamUsageResponse(
            snapshot_id=snapshot_id,
            teams=teams,
            unmapped_query_count=max(0, total_qc - mapped_qc),
            note=None,
        )


@router.get("/usage-by-app", response_model=AppUsageResponse)
def get_usage_by_app(
    snapshot_id: int | None = Query(None, description="Default: latest snapshot"),
) -> AppUsageResponse:
    """Usage statistics grouped by business application via schema/table mappings."""
    with Session(bind=engine) as session:
        if snapshot_id is None:
            snapshot_id = session.execute(
                select(Snapshot.snapshot_id).order_by(desc(Snapshot.snapshot_id)).limit(1)
            ).scalar_one_or_none()

        if snapshot_id is None:
            return AppUsageResponse(snapshot_id=None, applications=[], unmapped_query_count=0)

        total_qc: int = (
            session.execute(
                select(func.sum(UsageEvent.query_count)).where(
                    UsageEvent.snapshot_id == snapshot_id
                )
            ).scalar()
            or 0
        )

        # Load schema mappings: {UPPER(schema_name): [application_name, ...]}
        schema_map: dict[str, list[str]] = {}
        for m in session.execute(
            select(
                DatabaseApplicationMapping.schema_name,
                ApplicationEntity.application_name,
            ).join(
                ApplicationEntity,
                DatabaseApplicationMapping.application_id == ApplicationEntity.application_id,
            )
        ).all():
            schema_map.setdefault(m.schema_name.upper(), []).append(m.application_name)

        # Load table mappings: {UPPER("SCHEMA.TABLE"): [application_name, ...]}
        table_map: dict[str, list[str]] = {}
        for m in session.execute(
            select(
                TableApplicationMapping.schema_name,
                TableApplicationMapping.table_name,
                ApplicationEntity.application_name,
            ).join(
                ApplicationEntity,
                TableApplicationMapping.application_id == ApplicationEntity.application_id,
            )
        ).all():
            key = f"{m.schema_name.upper()}.{m.table_name.upper()}"
            table_map.setdefault(key, []).append(m.application_name)

        # Aggregate usage per application in Python (avoids complex SQL)
        agg: dict[str, dict] = {}

        usage_rows = session.execute(
            select(
                UsageEvent.schema_name,
                UsageEvent.object_name,
                UsageEvent.query_count,
                UsageEvent.user_count,
            ).where(UsageEvent.snapshot_id == snapshot_id)
        ).all()

        mapped_qc = 0
        for row in usage_rows:
            schema = (row.schema_name or "").upper()
            obj = (row.object_name or "").upper()
            qc = row.query_count or 0
            uc = row.user_count or 0

            apps_for_row: list[str] = table_map.get(obj) or schema_map.get(schema) or []
            if not apps_for_row:
                continue

            mapped_qc += qc
            for app_name in apps_for_row:
                if app_name not in agg:
                    agg[app_name] = {"query_count": 0, "user_count": 0, "objects": set()}
                agg[app_name]["query_count"] += qc
                agg[app_name]["user_count"] += uc
                agg[app_name]["objects"].add(obj)

        # Enrich with mapping counts
        app_schema_counts: dict[str, int] = {}
        app_table_counts: dict[str, int] = {}
        for schema_name, app_names in schema_map.items():
            for a in app_names:
                app_schema_counts[a] = app_schema_counts.get(a, 0) + 1
        for table_key, app_names in table_map.items():
            for a in app_names:
                app_table_counts[a] = app_table_counts.get(a, 0) + 1

        apps = sorted(
            [
                AppUsageRow(
                    application_name=name,
                    schema_count=app_schema_counts.get(name, 0),
                    table_count=app_table_counts.get(name, 0),
                    query_count=data["query_count"],
                    user_count=data["user_count"],
                )
                for name, data in agg.items()
            ],
            key=lambda r: r.query_count,
            reverse=True,
        )

        return AppUsageResponse(
            snapshot_id=snapshot_id,
            applications=apps,
            unmapped_query_count=max(0, total_qc - mapped_qc),
        )
