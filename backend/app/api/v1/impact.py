from __future__ import annotations

"""Impact API (v1).

Endpoints for individual and batch impact analysis.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.engine_registry import get_engine_states


router = APIRouter(prefix="/impact", tags=["impact"])


class ImpactItem(BaseModel):
    object_type: str
    object_name: str
    impact_type: str
    description: str
    depth: int = 0
    impact_score: float = 0.0


class ImpactSummary(BaseModel):
    direct_count: int
    indirect_count: int


class ImpactResponse(BaseModel):
    change_id: int
    direct_impact: list[ImpactItem]
    indirect_impact: list[ImpactItem]
    summary: ImpactSummary


class BatchImpactRequest(BaseModel):
    snapshot_from: int
    snapshot_to: int


class BatchChangeImpact(BaseModel):
    change_id: int
    object_identifier: str
    change_type: str
    severity: str
    is_breaking: bool
    direct_count: int = 0
    indirect_count: int = 0
    impact_score: float = 0.0
    query_count: int = 0
    user_count: int = 0


class BatchBlastRadius(BaseModel):
    total_impacted_nodes: int = 0
    max_depth: int = 0
    weighted_score: float = 0.0
    affected_schemas: List[str] = []
    affected_tables: List[str] = []


class BatchSummary(BaseModel):
    total_direct: int = 0
    total_indirect: int = 0
    breaking_count: int = 0
    overall_risk: str = "LOW"


class BatchImpactResponse(BaseModel):
    snapshot_from: int
    snapshot_to: int
    changes_analyzed: int
    blast_radius: BatchBlastRadius
    changes: List[BatchChangeImpact]
    summary: BatchSummary


def _get_node_name_map(snapshot_id: int) -> Dict[int, str]:
    """Build node_id -> object_name map for human-readable output."""
    from sqlalchemy.orm import Session
    from app.db.engine import engine
    from app.graph.graph_models import GraphNode

    with Session(bind=engine) as session:
        nodes = session.query(GraphNode).filter(
            GraphNode.snapshot_id == snapshot_id
        ).all()
        return {n.node_id: n.object_name for n in nodes}


@router.post(
    "/batch",
    status_code=status.HTTP_201_CREATED,
    response_model=BatchImpactResponse,
)
def execute_batch_impact(request: BatchImpactRequest) -> Dict[str, Any]:
    """Run impact analysis for ALL changes in a diff pair."""

    from app.graph.blast_radius import compute_batch_impact

    states = get_engine_states()
    if not states["graph_ready"]:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Graph/impact engine is stopped or not ready.")

    result = compute_batch_impact(request.snapshot_from, request.snapshot_to)
    return result.to_dict()


@router.post(
    "/{change_id}",
    status_code=status.HTTP_201_CREATED,
    response_model=ImpactResponse,
)
def execute_impact(change_id: int) -> ImpactResponse:
    """Run impact analysis for a single change."""

    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.db.engine import engine
    from app.diff.diff_models import ChangeEvent
    from app.graph.graph_diff_linker import link_changes_to_graph
    from app.graph.impact_analyzer import compute_downstream_impact, compute_upstream_impact
    from app.graph.impact_persister import persist_impact_events

    states = get_engine_states()
    if not states["graph_ready"]:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Graph/impact engine is stopped or not ready.")

    with Session(bind=engine) as session:
        change = session.execute(
            select(ChangeEvent).where(ChangeEvent.change_id == change_id)
        ).scalar_one_or_none()

    if change is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="change_id does not exist.")

    # Map the change onto the graph snapshot taken AFTER the change: upstream
    # and downstream edges only exist in that post-change topology.
    snapshot_to = change.snapshot_to
    mapping = link_changes_to_graph(snapshot_to)
    node_id = mapping.get(change_id)

    # Change targets an object that doesn't exist in the graph (e.g. a removed
    # table) — return empty impact rather than crashing.
    if node_id is None:
        return ImpactResponse(
            change_id=change_id,
            direct_impact=[],
            indirect_impact=[],
            summary=ImpactSummary(direct_count=0, indirect_count=0),
        )

    # Get node names for human-readable output
    node_names = _get_node_name_map(snapshot_to)

    # By convention, "direct impact" includes the changed object itself at
    # depth=0 — useful for UI callouts before listing dependents.
    direct_impact = [
        ImpactItem(
            object_type=change.object_type,
            object_name=change.object_identifier,
            impact_type=change.change_type,
            description=f"{change.change_type} on {change.object_identifier}",
            depth=0,
            impact_score=1.0,
        )
    ]

    # Compute downstream + upstream
    downstream = compute_downstream_impact(start_node_id=node_id, snapshot_id=snapshot_to)
    upstream = compute_upstream_impact(start_node_id=node_id, snapshot_id=snapshot_to)

    # Persist once per call — enables idempotent re-reads and powers the
    # alerts/intelligence views without recomputing the graph walk.
    all_impacts = downstream + upstream
    if all_impacts:
        persist_impact_events(change_id=change_id, snapshot_id=snapshot_to, impacts=all_impacts)

    indirect_items: list[ImpactItem] = []
    for item in downstream:
        nid = item["node_id"]
        name = node_names.get(nid, f"node:{nid}")
        obj_type = "TABLE" if "." in name else "SCHEMA"
        indirect_items.append(ImpactItem(
            object_type=obj_type,
            object_name=name,
            impact_type="DOWNSTREAM",
            description=f"Downstream dependency at depth {item['depth']}",
            depth=item["depth"],
            impact_score=item.get("impact_score", 0),
        ))

    for item in upstream:
        nid = item["node_id"]
        name = node_names.get(nid, f"node:{nid}")
        obj_type = "TABLE" if "." in name else "SCHEMA"
        indirect_items.append(ImpactItem(
            object_type=obj_type,
            object_name=name,
            impact_type="UPSTREAM",
            description=f"Upstream dependency at depth {item['depth']}",
            depth=item["depth"],
            impact_score=item.get("impact_score", 0),
        ))

    return ImpactResponse(
        change_id=change_id,
        direct_impact=direct_impact,
        indirect_impact=indirect_items,
        summary=ImpactSummary(
            direct_count=len(direct_impact),
            indirect_count=len(indirect_items),
        ),
    )
