from __future__ import annotations

"""Schema Tree API â€” returns hierarchical schema/table/column structure for a snapshot."""

from typing import Any, Dict, List

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot


router = APIRouter(prefix="/schema-tree", tags=["schema-tree"])


class ColumnItem(BaseModel):
    column_name: str
    data_type: str
    nullable: bool
    ordinal_position: int


class TableItem(BaseModel):
    table_name: str
    object_type: str
    columns: List[ColumnItem]


class SchemaItem(BaseModel):
    schema_name: str
    tables: List[TableItem]


class SchemaTreeResponse(BaseModel):
    snapshot_id: int
    schemas: List[SchemaItem]


@router.get("/{snapshot_id}", status_code=status.HTTP_200_OK, response_model=SchemaTreeResponse)
def get_schema_tree(snapshot_id: int) -> Dict[str, Any]:
    """Return the full schema tree for a snapshot."""
    # Three-level nested loop walks schemas -> tables -> columns. Acceptable
    # for tree rendering in the UI; if snapshots ever grow beyond a few
    # thousand columns, replace with a single flat query and group in memory.
    with Session(engine) as session:
        schemas = session.query(SchemaSnapshot).filter(
            SchemaSnapshot.snapshot_id == snapshot_id
        ).all()

        result_schemas = []
        for sch in schemas:
            tables = session.query(TableSnapshot).filter(
                TableSnapshot.schema_id == sch.schema_id
            ).all()

            result_tables = []
            for tbl in tables:
                columns = session.query(ColumnSnapshot).filter(
                    ColumnSnapshot.table_id == tbl.table_id
                ).order_by(ColumnSnapshot.ordinal_position).all()

                result_tables.append({
                    "table_name": tbl.table_name,
                    "object_type": tbl.object_type,
                    "columns": [
                        {
                            "column_name": col.column_name,
                            "data_type": col.data_type,
                            "nullable": col.nullable,
                            "ordinal_position": col.ordinal_position,
                        }
                        for col in columns
                    ],
                })

            result_schemas.append({
                "schema_name": sch.schema_name,
                "tables": result_tables,
            })

    return {"snapshot_id": snapshot_id, "schemas": result_schemas}
