"""Â§2.10 Reference Data importer.

Parses customer-supplied Excel (.xlsx) or CSV files and upserts the
org hierarchy and business-application mappings into the DB.

User/org format (any column order, case-insensitive headers):
    username | display_name | email | team | department

Application format:
    application_name | description | schema_name | table_name | owner_team

Missing optional columns are silently skipped. Rows with a blank required
field (username / application_name) are skipped and counted as warnings.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any

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


# â”€â”€ result dataclass â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@dataclass
class ImportResult:
    departments_upserted: int = 0
    teams_upserted: int = 0
    users_upserted: int = 0
    applications_upserted: int = 0
    schema_mappings_upserted: int = 0
    table_mappings_upserted: int = 0
    warnings: list[str] = field(default_factory=list)


# â”€â”€ helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _normalise_headers(raw_headers: list[str]) -> dict[str, str]:
    """Return {normalised_key: original_header} for flexible column matching."""
    aliases: dict[str, list[str]] = {
        "username":          ["username", "user", "user_name", "logon_name"],
        "display_name":      ["display_name", "name", "full_name", "user_display_name"],
        "email":             ["email", "email_address", "mail"],
        "team":              ["team", "team_name", "group"],
        "department":        ["department", "dept", "lob", "department_name", "line_of_business"],
        "application_name":  ["application_name", "application", "app", "app_name"],
        "description":       ["description", "desc", "notes"],
        "schema_name":       ["schema_name", "schema", "database", "database_name", "db"],
        "table_name":        ["table_name", "table", "object_name"],
        "owner_team":        ["owner_team", "owner", "owning_team"],
    }
    result: dict[str, str] = {}
    for header in raw_headers:
        normalised_header = header.strip().lower().replace(" ", "_")
        for key, candidates in aliases.items():
            if normalised_header in candidates and key not in result:
                result[key] = header
                break
    return result


def _parse_bytes(content: bytes, filename: str) -> tuple[list[str], list[dict[str, str]]]:
    """Return (headers, rows) from Excel or CSV bytes."""
    fname = filename.lower()
    if fname.endswith(".xlsx") or fname.endswith(".xls"):
        try:
            import openpyxl
        except ImportError as exc:
            raise RuntimeError("openpyxl is required to parse Excel files") from exc
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        headers = [str(c) if c is not None else "" for c in next(rows_iter, [])]
        rows = []
        for row in rows_iter:
            rows.append({h: (str(v).strip() if v is not None else "") for h, v in zip(headers, row)})
        wb.close()
        return headers, rows
    else:
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        headers = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]
        return headers, rows


def _cell(row: dict[str, str], alias_map: dict[str, str], key: str) -> str:
    """Get a cell value by logical key, returning "" if not mapped."""
    col = alias_map.get(key)
    return row.get(col, "").strip() if col else ""


# â”€â”€ public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def import_users(content: bytes, filename: str) -> ImportResult:
    """Upsert org hierarchy from user Excel/CSV. Idempotent."""
    result = ImportResult()
    headers, rows = _parse_bytes(content, filename)
    aliases = _normalise_headers(headers)

    if "username" not in aliases:
        result.warnings.append("No 'username' column found â€” file skipped.")
        return result

    with Session(engine) as session:
        dept_cache: dict[str, int] = {}
        team_cache: dict[str, int] = {}

        for i, row in enumerate(rows):
            username = _cell(row, aliases, "username")
            if not username:
                result.warnings.append(f"Row {i + 2}: blank username â€” skipped.")
                continue

            dept_name = _cell(row, aliases, "department")
            team_name = _cell(row, aliases, "team")

            # Upsert department
            dept_id: int | None = None
            if dept_name:
                if dept_name not in dept_cache:
                    existing = session.query(DepartmentEntity).filter_by(
                        department_name=dept_name
                    ).first()
                    if not existing:
                        dept = DepartmentEntity(department_name=dept_name)
                        session.add(dept)
                        session.flush()
                        result.departments_upserted += 1
                        dept_cache[dept_name] = dept.department_id
                    else:
                        dept_cache[dept_name] = existing.department_id
                dept_id = dept_cache[dept_name]

            # Upsert team
            team_id: int | None = None
            if team_name:
                if team_name not in team_cache:
                    existing = session.query(TeamEntity).filter_by(team_name=team_name).first()
                    if not existing:
                        team = TeamEntity(team_name=team_name, department_id=dept_id)
                        session.add(team)
                        session.flush()
                        result.teams_upserted += 1
                        team_cache[team_name] = team.team_id
                    else:
                        # Update department linkage if it was missing before
                        if dept_id and not existing.department_id:
                            existing.department_id = dept_id
                        team_cache[team_name] = existing.team_id
                team_id = team_cache[team_name]

            # Upsert user
            existing_user = session.query(UserEntity).filter_by(username=username).first()
            if not existing_user:
                user = UserEntity(
                    username=username,
                    display_name=_cell(row, aliases, "display_name") or None,
                    email=_cell(row, aliases, "email") or None,
                    team_id=team_id,
                )
                session.add(user)
                result.users_upserted += 1
            else:
                if team_id and not existing_user.team_id:
                    existing_user.team_id = team_id
                dn = _cell(row, aliases, "display_name")
                if dn and not existing_user.display_name:
                    existing_user.display_name = dn
                em = _cell(row, aliases, "email")
                if em and not existing_user.email:
                    existing_user.email = em

        session.commit()

    return result


def import_applications(content: bytes, filename: str) -> ImportResult:
    """Upsert application metadata from Excel/CSV. Idempotent."""
    result = ImportResult()
    headers, rows = _parse_bytes(content, filename)
    aliases = _normalise_headers(headers)

    if "application_name" not in aliases:
        result.warnings.append("No 'application_name' column found â€” file skipped.")
        return result

    with Session(engine) as session:
        app_cache: dict[str, int] = {}
        team_cache: dict[str, int] = {}

        for i, row in enumerate(rows):
            app_name = _cell(row, aliases, "application_name")
            if not app_name:
                result.warnings.append(f"Row {i + 2}: blank application_name â€” skipped.")
                continue

            owner_team_name = _cell(row, aliases, "owner_team")
            owner_team_id: int | None = None
            if owner_team_name:
                if owner_team_name not in team_cache:
                    t = session.query(TeamEntity).filter_by(team_name=owner_team_name).first()
                    if t:
                        team_cache[owner_team_name] = t.team_id
                owner_team_id = team_cache.get(owner_team_name)

            # Upsert application
            if app_name not in app_cache:
                existing = session.query(ApplicationEntity).filter_by(
                    application_name=app_name
                ).first()
                if not existing:
                    app = ApplicationEntity(
                        application_name=app_name,
                        description=_cell(row, aliases, "description") or None,
                        owner_team_id=owner_team_id,
                    )
                    session.add(app)
                    session.flush()
                    result.applications_upserted += 1
                    app_cache[app_name] = app.application_id
                else:
                    if owner_team_id and not existing.owner_team_id:
                        existing.owner_team_id = owner_team_id
                    app_cache[app_name] = existing.application_id

            app_id = app_cache[app_name]

            # Schema mapping
            schema = _cell(row, aliases, "schema_name").upper()
            table = _cell(row, aliases, "table_name").upper()

            if schema:
                # Database-level mapping
                existing_db = (
                    session.query(DatabaseApplicationMapping)
                    .filter_by(schema_name=schema, application_id=app_id)
                    .first()
                )
                if not existing_db:
                    session.add(DatabaseApplicationMapping(schema_name=schema, application_id=app_id))
                    result.schema_mappings_upserted += 1

                if table:
                    existing_tbl = (
                        session.query(TableApplicationMapping)
                        .filter_by(schema_name=schema, table_name=table, application_id=app_id)
                        .first()
                    )
                    if not existing_tbl:
                        session.add(
                            TableApplicationMapping(
                                schema_name=schema, table_name=table, application_id=app_id
                            )
                        )
                        result.table_mappings_upserted += 1

        session.commit()

    return result
