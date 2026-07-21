"""§2.16.b — Import validation pass.

Called from dict_persister.run_post_ingest_pipeline() after all rows are
committed.  Reads table_snapshot + column_snapshot for a given snapshot_id,
runs a set of structural checks, and persists the result into:
  - snapshot.validation_warnings (JSON list)
  - snapshot.import_status → 'committed' (pass) | 'failed' (hard errors)
  - staging_table_import.row_status updated per object

Validation rules
----------------
HARD errors (import_status = 'failed' if ANY are present):
  - DUPLICATE_TABLE : same (schema_name, table_name) pair appears more than
    once inside the snapshot.

WARNINGS (import_status stays 'committed', logged in validation_warnings):
  - NULL_SCHEMA : table_name present but schema_name is empty/null.
  - UNKNOWN_TYPE : data_type not in the recognized Teradata type vocabulary.
  - DDL_CONFLICT : (future §2.4 absorption) multiple DDL texts for same table.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot
from app.db.models.staging import StagingTableImport, StagingColumnImport

logger = logging.getLogger(__name__)

# Teradata / common SQL type tokens that SCION considers valid.
_KNOWN_TYPES: frozenset[str] = frozenset(
    [
        "INTEGER", "INT", "SMALLINT", "BYTEINT", "BIGINT",
        "FLOAT", "REAL", "DOUBLE PRECISION", "NUMBER", "NUMERIC", "DECIMAL",
        "CHAR", "CHARACTER", "VARCHAR", "CHARACTER VARYING", "LONG VARCHAR",
        "CLOB", "BLOB",
        "BYTE", "VARBYTE", "LONG VARBYTE",
        "DATE", "TIME", "TIMESTAMP", "TIME WITH TIME ZONE", "TIMESTAMP WITH TIME ZONE",
        "INTERVAL", "PERIOD",
        "BOOLEAN",
        "JSON", "XML", "ST_GEOMETRY", "MBR",
    ]
)


def _is_known_type(data_type: str) -> bool:
    """Return True if the base type token is in the known vocabulary."""
    base = data_type.split("(")[0].split(" CHARACTER")[0].strip().upper()
    return base in _KNOWN_TYPES


def validate_import(snapshot_id: int, session: Session) -> dict[str, Any]:
    """Run all validation rules for a freshly-committed snapshot.

    Returns a dict with keys:
        status          : 'committed' | 'failed'
        hard_errors     : int
        warnings        : int
        issues          : list[dict]   (each: type, severity, message, object_name?)
        tables_checked  : int
        columns_checked : int
    """
    snap = session.get(Snapshot, snapshot_id)
    if snap is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")

    issues: list[dict[str, Any]] = []
    hard_errors = 0

    # ── collect all table rows for this snapshot ─────────────────────
    rows = (
        session.query(TableSnapshot, SchemaSnapshot)
        .join(SchemaSnapshot, TableSnapshot.schema_id == SchemaSnapshot.schema_id)
        .filter(SchemaSnapshot.snapshot_id == snapshot_id)
        .all()
    )
    tables_checked = len(rows)

    # Seen set for duplicate detection
    seen: dict[tuple[str, str], int] = {}  # (schema, table) → count

    for tbl, sch in rows:
        key = (sch.schema_name or "", tbl.table_name or "")
        seen[key] = seen.get(key, 0) + 1

        if not sch.schema_name:
            issues.append(
                {
                    "type": "NULL_SCHEMA",
                    "severity": "WARNING",
                    "message": f"Table '{tbl.table_name}' has no schema name",
                    "object_name": tbl.table_name,
                }
            )

    # Report duplicates (HARD)
    for (schema, table), count in seen.items():
        if count > 1:
            hard_errors += 1
            issues.append(
                {
                    "type": "DUPLICATE_TABLE",
                    "severity": "ERROR",
                    "message": f"'{schema}.{table}' appears {count} times in snapshot",
                    "object_name": f"{schema}.{table}",
                }
            )

    # ── column type validation ────────────────────────────────────────
    # Use two targeted queries instead of materialising all column rows.
    # At Transcend scale (9.8M columns) a .all() would allocate ~4 GB of
    # ORM objects; we only need the total count and the set of distinct
    # data_type values that fail the vocabulary check.
    schema_id_subq = (
        select(SchemaSnapshot.schema_id)
        .where(SchemaSnapshot.snapshot_id == snapshot_id)
        .scalar_subquery()
    )
    table_id_subq = (
        select(TableSnapshot.table_id)
        .where(TableSnapshot.schema_id.in_(schema_id_subq))
        .scalar_subquery()
    )

    columns_checked = (
        session.execute(
            select(func.count(ColumnSnapshot.column_id))
            .where(ColumnSnapshot.table_id.in_(table_id_subq))
        ).scalar()
        or 0
    )

    distinct_types = session.execute(
        select(ColumnSnapshot.data_type)
        .where(
            ColumnSnapshot.table_id.in_(table_id_subq),
            ColumnSnapshot.data_type.isnot(None),
        )
        .distinct()
    ).scalars().all()

    unknown_types: set[str] = set()
    for dt in distinct_types:
        if not _is_known_type(dt):
            unknown_types.add(dt)

    for dt in sorted(unknown_types):
        issues.append(
            {
                "type": "UNKNOWN_TYPE",
                "severity": "WARNING",
                "message": f"Unrecognized data type '{dt}' (may be vendor-specific)",
                "object_name": None,
            }
        )

    status = "failed" if hard_errors > 0 else "committed"

    # ── persist results ───────────────────────────────────────────────
    snap.import_status = status
    snap.validation_warnings = issues if issues else None

    # Update staging_table_import row_status if rows exist
    staging_rows = (
        session.query(StagingTableImport)
        .filter(StagingTableImport.snapshot_id == snapshot_id)
        .all()
    )
    if staging_rows:
        dup_keys = {
            (sch, tbl)
            for (sch, tbl), cnt in seen.items()
            if cnt > 1
        }
        for sr in staging_rows:
            key = (sr.schema_name, sr.table_name)
            if key in dup_keys:
                sr.row_status = "rejected"
                sr.validation_errors = [
                    {"type": "DUPLICATE_TABLE", "message": f"Duplicate: {key[0]}.{key[1]}"}
                ]
            else:
                sr.row_status = "accepted"

    session.flush()

    result = {
        "status": status,
        "hard_errors": hard_errors,
        "warnings": len(issues) - hard_errors,
        "issues": issues,
        "tables_checked": tables_checked,
        "columns_checked": columns_checked,
    }

    logger.info(
        "[staging-validator] snapshot=%s status=%s tables=%d cols=%d errors=%d warnings=%d",
        snapshot_id,
        status,
        tables_checked,
        columns_checked,
        hard_errors,
        len(issues) - hard_errors,
    )
    return result
