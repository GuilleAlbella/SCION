"""Column-level lineage API endpoint.

Exposes the attribute_lineage table (Tier 1/2 data from the DataDNA parser)
via a REST interface. Complementary to the graph FEEDS edges (table-to-table);
this endpoint gives the finer-grained column-to-column view.

Natural key format for attributes: "SCHEMA.TABLE|COLUMN_NAME"
"""
from __future__ import annotations

from collections import deque
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
    step_natural_key: Optional[str] = None


class IndirectEdge(BaseModel):
    """A column used in a filter or join condition — no direct target column.

    Rows where target_attribute_natural_key == "NOT APPLICABLE" represent
    SQL predicates (WHERE filters, JOIN conditions, GROUP BY keys, HAVING
    clauses) that affect *which rows* flow to the target, but don't map the
    column value to a named target column.  The parser still records the
    source column and the SQL fragment (expression) so analysts can trace
    indirect data influence.
    """

    source_column_key: str
    source_column_name: str
    transformation_type: Optional[str]
    expression: Optional[str]


class ColumnLineageEntry(BaseModel):
    column_name: str
    upstream: list[ColumnEdge]
    downstream: list[ColumnEdge]
    indirect: list[IndirectEdge] = []


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

    # col_map[col_upper] = {
    #   "name": str,
    #   "upstream": dict[src_key, ColumnEdge],    — deduped by partner key
    #   "downstream": dict[tgt_key, ColumnEdge],  — deduped by partner key
    #   "indirect": list[IndirectEdge],            — filter/join predicates (not deduped)
    # }
    # Rows where target == "NOT APPLICABLE" are parser-encoded indirect impacts
    # (filter conditions, JOIN predicates, GROUP BY keys) that affect *which rows*
    # flow but do not map the column value to a named target.  They are separated
    # from the direct upstream/downstream edges so the UI can show them in a
    # dedicated collapsible section.
    _NOT_APPLICABLE = "NOT APPLICABLE"

    col_map: dict[str, dict] = {}

    def _init_entry(col_name: str) -> dict:
        return {"name": col_name, "upstream": {}, "downstream": {}, "indirect": []}

    def _edge(row: AttributeLineage, key: str) -> ColumnEdge:
        table_key, col_name = _split_key(key)
        return ColumnEdge(
            column_key=key,
            table_key=table_key,
            column_name=col_name,
            expression=row.expression,
            transformation_type=row.transformation_type,
            tier=row.tier,
            step_natural_key=row.step_natural_key,
        )

    for row in rows:
        src = row.source_attribute_natural_key or ""
        tgt = row.target_attribute_natural_key or ""

        if src.upper().startswith(prefix):
            _, col = _split_key(src)
            key = col.upper()
            if key not in col_map:
                col_map[key] = _init_entry(col)

            if tgt.upper().startswith(_NOT_APPLICABLE):
                # Indirect: this column is used in a predicate, not as a value source
                col_map[key]["indirect"].append(IndirectEdge(
                    source_column_key=src,
                    source_column_name=col,
                    transformation_type=row.transformation_type,
                    expression=row.expression,
                ))
            else:
                tgt_upper = tgt.upper()
                if tgt_upper not in col_map[key]["downstream"]:
                    col_map[key]["downstream"][tgt_upper] = _edge(row, tgt)

        if tgt.upper().startswith(prefix):
            _, col = _split_key(tgt)
            key = col.upper()
            if key not in col_map:
                col_map[key] = _init_entry(col)
            src_upper = src.upper()
            if src_upper not in col_map[key]["upstream"]:
                col_map[key]["upstream"][src_upper] = _edge(row, src)

    columns = [
        ColumnLineageEntry(
            column_name=v["name"],
            upstream=list(v["upstream"].values()),
            downstream=list(v["downstream"].values()),
            indirect=v["indirect"],
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


# ── Traverse models ────────────────────────────────────────────────────────────

class TraverseNode(BaseModel):
    column_key: str
    table_key: str
    column_name: str
    depth: int
    path: list[str]          # ordered column_keys from root to this node
    transformation_type: Optional[str]
    tier: Optional[str]


class ColumnTraverseResponse(BaseModel):
    column_key: str
    snapshot_id: int
    direction: str
    nodes: list[TraverseNode]
    total_hops: int


@router.get("/columns/traverse", response_model=ColumnTraverseResponse)
def traverse_column_lineage(
    snapshot_id: int = Query(...),
    column_key: str = Query(..., description="e.g. SCHEMA.TABLE|COLUMN_NAME"),
    direction: str = Query("downstream", description="downstream | upstream"),
    max_depth: int = Query(10, ge=1, le=20),
):
    """BFS from a specific column following attribute_lineage edges.

    Returns all reachable columns with their depth and the ordered path
    from the root column to each node.  Rows with target == 'NOT APPLICABLE'
    (indirect predicates) are skipped so the graph only shows value-carrying
    lineage.
    """
    _NOT_APPLICABLE = "NOT APPLICABLE"

    # frontier: upper_key → (original_case_key, depth, path)
    frontier: dict[str, tuple[str, int, list[str]]] = {
        column_key.upper(): (column_key, 0, [column_key])
    }
    visited: set[str] = {column_key.upper()}
    result_nodes: list[TraverseNode] = []
    total_hops = 0

    with Session(bind=engine) as db:
        for _ in range(max_depth):
            if not frontier:
                break

            frontier_keys = list(frontier.keys())

            if direction == "downstream":
                rows = db.query(AttributeLineage).filter(
                    AttributeLineage.snapshot_id == snapshot_id,
                    func.upper(AttributeLineage.source_attribute_natural_key).in_(frontier_keys),
                ).all()
            else:
                rows = db.query(AttributeLineage).filter(
                    AttributeLineage.snapshot_id == snapshot_id,
                    func.upper(AttributeLineage.target_attribute_natural_key).in_(frontier_keys),
                ).all()

            # Build lookup: frontier_upper → list of (next_key, transformation_type, tier)
            next_map: dict[str, list[tuple[str, Optional[str], Optional[str]]]] = {}
            for row in rows:
                src = row.source_attribute_natural_key or ""
                tgt = row.target_attribute_natural_key or ""

                if direction == "downstream":
                    from_upper = src.upper()
                    next_key = tgt
                else:
                    from_upper = tgt.upper()
                    next_key = src

                next_upper = next_key.upper()
                if next_upper.startswith(_NOT_APPLICABLE):
                    continue
                if next_upper in visited:
                    continue
                if from_upper not in frontier:
                    continue

                if from_upper not in next_map:
                    next_map[from_upper] = []
                next_map[from_upper].append((next_key, row.transformation_type, row.tier))

            next_frontier: dict[str, tuple[str, int, list[str]]] = {}
            for from_upper, candidates in next_map.items():
                _orig_from, depth, path = frontier[from_upper]
                new_depth = depth + 1
                seen_next: set[str] = set()
                for next_key, transf_type, tier in candidates:
                    next_upper = next_key.upper()
                    if next_upper in seen_next:
                        continue
                    seen_next.add(next_upper)
                    if next_upper not in next_frontier:
                        next_frontier[next_upper] = (next_key, new_depth, path + [next_key])
                        table_key, col_name = _split_key(next_key)
                        result_nodes.append(TraverseNode(
                            column_key=next_key,
                            table_key=table_key,
                            column_name=col_name,
                            depth=new_depth,
                            path=path + [next_key],
                            transformation_type=transf_type,
                            tier=tier,
                        ))

            if not next_frontier:
                break

            total_hops = max(d for _, d, _ in next_frontier.values())
            for upper in next_frontier:
                visited.add(upper)
            frontier = next_frontier

    return ColumnTraverseResponse(
        column_key=column_key,
        snapshot_id=snapshot_id,
        direction=direction,
        nodes=result_nodes,
        total_hops=total_hops,
    )
