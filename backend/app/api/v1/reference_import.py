"""Â§2.10 Reference Data â€” import endpoints.

POST /reference-import/users
    Upload Excel (.xlsx) or CSV with org hierarchy (username / team / department).

POST /reference-import/applications
    Upload Excel (.xlsx) or CSV with app metadata (application_name / schema / table).

GET /reference-import/status
    Counts of imported entities.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import func, select
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
from app.pipelines.reference_importer import import_applications, import_users

router = APIRouter(prefix="/reference-import", tags=["reference"])


# â”€â”€ response schemas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class UserImportResponse(BaseModel):
    departments_upserted: int
    teams_upserted: int
    users_upserted: int
    warnings: list[str]


class AppImportResponse(BaseModel):
    applications_upserted: int
    schema_mappings_upserted: int
    table_mappings_upserted: int
    warnings: list[str]


class ReferenceStatus(BaseModel):
    departments: int
    teams: int
    users: int
    applications: int
    schema_mappings: int
    table_mappings: int


# â”€â”€ endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@router.post("/users", response_model=UserImportResponse)
async def upload_users(file: UploadFile = File(...)) -> UserImportResponse:
    """Import org hierarchy from Excel or CSV."""
    fname = file.filename or "upload.csv"
    if not (fname.lower().endswith(".xlsx") or fname.lower().endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only .xlsx and .csv files are accepted.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    result = import_users(content, fname)
    return UserImportResponse(
        departments_upserted=result.departments_upserted,
        teams_upserted=result.teams_upserted,
        users_upserted=result.users_upserted,
        warnings=result.warnings,
    )


@router.post("/applications", response_model=AppImportResponse)
async def upload_applications(file: UploadFile = File(...)) -> AppImportResponse:
    """Import business application metadata from Excel or CSV."""
    fname = file.filename or "upload.csv"
    if not (fname.lower().endswith(".xlsx") or fname.lower().endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only .xlsx and .csv files are accepted.")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    result = import_applications(content, fname)
    return AppImportResponse(
        applications_upserted=result.applications_upserted,
        schema_mappings_upserted=result.schema_mappings_upserted,
        table_mappings_upserted=result.table_mappings_upserted,
        warnings=result.warnings,
    )


@router.get("/status", response_model=ReferenceStatus)
def get_reference_status() -> ReferenceStatus:
    """Return counts of all imported reference entities."""
    with Session(engine) as session:
        return ReferenceStatus(
            departments=session.execute(
                select(func.count(DepartmentEntity.department_id))
            ).scalar() or 0,
            teams=session.execute(
                select(func.count(TeamEntity.team_id))
            ).scalar() or 0,
            users=session.execute(
                select(func.count(UserEntity.user_id))
            ).scalar() or 0,
            applications=session.execute(
                select(func.count(ApplicationEntity.application_id))
            ).scalar() or 0,
            schema_mappings=session.execute(
                select(func.count(DatabaseApplicationMapping.mapping_id))
            ).scalar() or 0,
            table_mappings=session.execute(
                select(func.count(TableApplicationMapping.mapping_id))
            ).scalar() or 0,
        )
