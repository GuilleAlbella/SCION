from __future__ import annotations

"""Columns API — PII classification and retrieval.

Two endpoints:
  POST /columns/classify  — run TAISA PII analysis over unclassified columns
                            in a snapshot (or a specific table), caching results
                            on column_snapshot.pii_label / pii_confidence.
  GET  /columns/pii       — return cached PII data for one SCHEMA.TABLE object.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.column_snapshot import ColumnSnapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.engine_registry import get_taisa_client

router = APIRouter(prefix="/columns", tags=["columns"])


class PiiEntry(BaseModel):
    column_id: int
    column_name: str
    data_type: str
    pii_label: Optional[str]
    pii_confidence: Optional[float]
    pii_classified_at: Optional[str]


class PiiResponse(BaseModel):
    object: str
    snapshot_id: int
    columns: List[PiiEntry]


class ClassifyResponse(BaseModel):
    snapshot_id: int
    classified: int
    skipped: int
    errors: int


@router.get("/pii", response_model=PiiResponse)
def get_column_pii(
    snapshot_id: int = Query(...),
    object: str = Query(..., description="SCHEMA.TABLE identifier"),
) -> PiiResponse:
    """Return cached PII classification for all columns of a specific table."""
    parts = object.split(".", 1)
    schema_name = parts[0] if len(parts) >= 2 else None
    table_name = parts[1] if len(parts) >= 2 else parts[0]

    with Session(engine) as db:
        stmt = (
            select(TableSnapshot.table_id)
            .join(SchemaSnapshot, TableSnapshot.schema_id == SchemaSnapshot.schema_id)
            .where(
                SchemaSnapshot.snapshot_id == snapshot_id,
                TableSnapshot.table_name.ilike(table_name),
            )
        )
        if schema_name:
            stmt = stmt.where(SchemaSnapshot.schema_name.ilike(schema_name))

        row = db.execute(stmt).first()
        if not row:
            return PiiResponse(object=object, snapshot_id=snapshot_id, columns=[])

        table_id = row[0]
        cols = db.execute(
            select(ColumnSnapshot)
            .where(ColumnSnapshot.table_id == table_id)
            .order_by(ColumnSnapshot.ordinal_position)
        ).scalars().all()

        return PiiResponse(
            object=object,
            snapshot_id=snapshot_id,
            columns=[
                PiiEntry(
                    column_id=c.column_id,
                    column_name=c.column_name,
                    data_type=c.data_type,
                    pii_label=c.pii_label,
                    pii_confidence=c.pii_confidence,
                    pii_classified_at=(
                        c.pii_classified_at.isoformat() if c.pii_classified_at else None
                    ),
                )
                for c in cols
            ],
        )


@router.post("/classify", response_model=ClassifyResponse)
def classify_columns(
    snapshot_id: int = Query(...),
    limit: int = Query(500, ge=1, le=5000, description="Max columns to classify in this call"),
    force: bool = Query(False, description="Re-classify already-classified columns"),
    object: Optional[str] = Query(
        None, description="Scope to a single SCHEMA.TABLE — omit to process all tables"
    ),
) -> ClassifyResponse:
    """Batch-classify columns using TAISA PII analysis, caching results on column_snapshot."""
    taisa = get_taisa_client()
    classified_at = datetime.now(timezone.utc)
    classified = 0
    skipped = 0
    errors = 0

    with Session(engine) as db:
        table_stmt = (
            select(
                TableSnapshot.table_id,
                TableSnapshot.table_name,
                SchemaSnapshot.schema_name,
            )
            .join(SchemaSnapshot, TableSnapshot.schema_id == SchemaSnapshot.schema_id)
            .where(SchemaSnapshot.snapshot_id == snapshot_id)
        )
        if object:
            parts = object.split(".", 1)
            if len(parts) >= 2:
                table_stmt = table_stmt.where(
                    SchemaSnapshot.schema_name.ilike(parts[0]),
                    TableSnapshot.table_name.ilike(parts[1]),
                )

        tables = db.execute(table_stmt).all()

        for table_id, table_name, schema_name in tables:
            remaining = limit - classified
            if remaining <= 0:
                # Budget exhausted — skip remaining tables without querying them.
                # We don't count precise skipped-column totals past this point,
                # but avoid issuing N more SQL queries for tables we won't classify.
                break

            col_stmt = select(ColumnSnapshot).where(
                ColumnSnapshot.table_id == table_id
            )
            if not force:
                col_stmt = col_stmt.where(ColumnSnapshot.pii_classified_at.is_(None))

            cols = db.execute(col_stmt).scalars().all()
            if not cols:
                continue

            to_classify = cols[:remaining]
            skipped += len(cols) - len(to_classify)

            batch_input = [
                {"column_name": c.column_name, "data_type": c.data_type}
                for c in to_classify
            ]

            try:
                results = taisa.classify_column_pii_batch(
                    table_name=table_name,
                    schema_name=schema_name,
                    columns=batch_input,
                )
                result_map = {r.column_name.upper(): r for r in results}

                for col in to_classify:
                    r = result_map.get(col.column_name.upper())
                    if r:
                        col.pii_label = r.pii_label
                        col.pii_confidence = r.confidence
                        col.pii_classified_at = classified_at
                        classified += 1
            except Exception:
                errors += len(batch_input)

        db.commit()

    return ClassifyResponse(
        snapshot_id=snapshot_id,
        classified=classified,
        skipped=skipped,
        errors=errors,
    )
