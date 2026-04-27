from __future__ import annotations

"""Graph API (v1).

Read-only access to the structural system graph for a given snapshot.
Includes node metrics (degree, fragility) and semantic edge types.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.graph.graph_models import GraphEdge, GraphNode


router = APIRouter(prefix="/graph", tags=["graph"])


class GraphNodeItem(BaseModel):
    node_id: str
    object_type: str
    object_name: str
    schema_name: str
    metrics: Optional[Dict[str, Any]] = None


class GraphEdgeItem(BaseModel):
    source: str
    target: str
    type: str


class GraphResponse(BaseModel):
    snapshot_id: int
    nodes: List[GraphNodeItem]
    edges: List[GraphEdgeItem]


@router.get("/{snapshot_id}", status_code=status.HTTP_200_OK, response_model=GraphResponse)
def get_graph(snapshot_id: int) -> Dict[str, Any]:
    """Return the structural graph for a given snapshot with metrics."""

    with Session(bind=engine) as session:
        node_rows = session.execute(
            select(GraphNode).where(GraphNode.snapshot_id == snapshot_id)
        ).scalars().all()
        edge_rows = session.execute(
            select(GraphEdge).where(GraphEdge.snapshot_id == snapshot_id)
        ).scalars().all()

    # Build uid lookup for edges that only have node_ids
    uid_by_id: Dict[int, str] = {}
    for row in node_rows:
        uid_by_id[row.node_id] = row.node_uid or str(row.node_id)

    nodes: List[Dict[str, Any]] = [
        {
            "node_id": row.node_uid or str(row.node_id),
            "object_type": row.object_type,
            "object_name": row.object_name,
            "schema_name": row.schema_name,
            "metrics": row.node_metadata,
        }
        for row in node_rows
    ]

    edges: List[Dict[str, Any]] = []
    for edge in edge_rows:
        source_uid = edge.from_node_uid or uid_by_id.get(edge.source_node_id, str(edge.source_node_id))
        target_uid = edge.to_node_uid or uid_by_id.get(edge.target_node_id, str(edge.target_node_id))
        edges.append({
            "source": source_uid,
            "target": target_uid,
            "type": edge.edge_type or edge.relationship_type or "DEPENDS_ON",
        })

    return {
        "snapshot_id": snapshot_id,
        "nodes": nodes,
        "edges": edges,
    }
