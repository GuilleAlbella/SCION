"""Column-level lineage API endpoint.

Exposes the attribute_lineage table (Tier 1/2 data from the DataDNA parser)
via a REST interface. Complementary to the graph FEEDS edges (table-to-table);
this endpoint gives the finer-grained column-to-column view.

Natural key format for attributes: "SCHEMA.TABLE|COLUMN_NAME"
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.attribute_lineage import AttributeLineage

router = APIRouter(prefix="/lineage", tags=["lineage"])


class ColumnEdge(BaseModel):
    column_key: str
    table_key: str
    column_name: str
    expression: Optional[str]
    transformation_type: Optional[str]
    tier: Optional[str]


class ColumnLineageEntry(BaseModel):
    column_name: str
    upstream: list[ColumnEdge]
    downstream: list[ColumnEdge]


class ColumnLineageResponse(BaseModel):
    object: str
    snapshot_id: int
    columns: list[ColumnLineageEntry]
    total_edges: int


def _split_key(key: str) -> tuple[str, str]:
    """'SCHEMA.TABLE|COL' → ('SCHEMA.TABLE', 'COL')"""
    if "|" in key:
        table, col = key.split("|", 1)
        return table, col
    return key, ""


@router.get("/columns", response_model=ColumnLineageResponse)
def get_column_lineage(
    snapshot_id: int = Query(...),
    object: str = Query(..., description="Object identifier, e.g. SCHEMA.TABLE"),
    tier: Optional[str] = Query(None, description="Filter by tier: TIER1 or TIER2"),
):
    """Return column-level lineage for a given table or view.

    Queries attribute_lineage for all Tier 1/2 edges where the source or
    target column belongs to the requested object. Groups results by column
    and separates upstream (things that feed this column) from downstream
    (things this column feeds).
    """
    obj_upper = object.upper()
    prefix = obj_upper + "|"

    with Session(bind=engine) as db:
        q = db.query(AttributeLineage).filter(
            AttributeLineage.snapshot_id == snapshot_id,
            or_(
                func.upper(AttributeLineage.source_attribute_natural_key).like(prefix + "%"),
                func.upper(AttributeLineage.target_attribute_natural_key).like(prefix + "%"),
            ),
        )
        if tier:
            q = q.filter(func.upper(AttributeLineage.tier) == tier.upper())

        rows = q.all()

    # col_map[col_upper] = {"name": str, "upstream": dict[tgt_key, ColumnEdge], "downstream": dict[tgt_key, ColumnEdge]}
    # Using dicts keyed by the partner column_key deduplicates rows that the parser
    # emitted multiple times for the same (source, target) pair across different steps.
    col_map: dict[str, dict] = {}

    def _edge(row: AttributeLineage, key: str) -> ColumnEdge:
        table_key, col_name = _split_key(key)
        return ColumnEdge(
            column_key=key,
            table_key=table_key,
            column_name=col_name,
            expression=row.expression,
            transformation_type=row.transformation_type,
            tier=row.tier,
        )

    for row in rows:
        src = row.source_attribute_natural_key or ""
        tgt = row.target_attribute_natural_key or ""

        if src.upper().startswith(prefix):
            _, col = _split_key(src)
            key = col.upper()
            if key not in col_map:
                col_map[key] = {"name": col, "upstream": {}, "downstream": {}}
            tgt_upper = tgt.upper()
            if tgt_upper not in col_map[key]["downstream"]:
                col_map[key]["downstream"][tgt_upper] = _edge(row, tgt)

        if tgt.upper().startswith(prefix):
            _, col = _split_key(tgt)
            key = col.upper()
            if key not in col_map:
                col_map[key] = {"name": col, "upstream": {}, "downstream": {}}
            src_upper = src.upper()
            if src_upper not in col_map[key]["upstream"]:
                col_map[key]["upstream"][src_upper] = _edge(row, src)

    columns = [
        ColumnLineageEntry(
            column_name=v["name"],
            upstream=list(v["upstream"].values()),
            downstream=list(v["downstream"].values()),
        )
        for v in sorted(col_map.values(), key=lambda x: x["name"].upper())
    ]

    total_edges = sum(len(c.upstream) + len(c.downstream) for c in columns)

    return ColumnLineageResponse(
        object=object,
        snapshot_id=snapshot_id,
        columns=columns,
        total_edges=total_edges,
    )
