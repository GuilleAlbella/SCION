from __future__ import annotations

"""Simulation API (v1) — "what if" analysis.

Lets a user pick a hypothetical change (e.g. "change this column type",
"drop this table") and see the blast radius + TAISA analysis WITHOUT
applying the change. Uses the existing graph to compute downstream
dependencies and joins with usage data to estimate SQL impact.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.graph.graph_models import GraphNode, GraphEdge
from app.graph.impact_analyzer import compute_downstream_impact, compute_upstream_impact


router = APIRouter(prefix="/simulation", tags=["simulation"])


HYPOTHETICAL_CHANGE_TYPES = [
    "TABLE_REMOVED",
    "TABLE_TYPE_CHANGED",
    "COLUMN_REMOVED",
    "COLUMN_TYPE_CHANGED",
    "COLUMN_NULLABILITY_CHANGED",
]


class SimulationRequest(BaseModel):
    object_identifier: str          # e.g. "core_banking.accounts" or "core_banking.accounts.account_id"
    change_type: str                # one of HYPOTHETICAL_CHANGE_TYPES
    snapshot_id: int                # which snapshot to simulate against
    new_value: Optional[str] = None # e.g. new data type (for informational purposes)


class SimulationImpact(BaseModel):
    object_name: str
    impact_level: str    # DOWNSTREAM / UPSTREAM
    depth: int


class SimulationResponse(BaseModel):
    object_identifier: str
    change_type: str
    snapshot_id: int
    is_breaking: bool
    severity: str
    direct_impacts: List[SimulationImpact]
    indirect_impacts: List[SimulationImpact]
    queries_affected: int
    users_affected: int
    recommendation: str
    risk_level: str


# Map change_type to severity + breaking classification (matches DiffEngine logic)
_SEVERITY_MAP = {
    "TABLE_REMOVED": "HIGH",
    "TABLE_TYPE_CHANGED": "HIGH",
    "COLUMN_REMOVED": "HIGH",
    "COLUMN_TYPE_CHANGED": "MEDIUM",
    "COLUMN_NULLABILITY_CHANGED": "MEDIUM",
}
_BREAKING = {
    "TABLE_REMOVED": True,
    "TABLE_TYPE_CHANGED": True,
    "COLUMN_REMOVED": True,
    "COLUMN_TYPE_CHANGED": True,
    "COLUMN_NULLABILITY_CHANGED": False,
}


@router.post("", status_code=status.HTTP_200_OK, response_model=SimulationResponse)
def simulate_change(request: SimulationRequest) -> Dict[str, Any]:
    """Simulate a hypothetical change and return its blast radius + risk assessment."""

    if request.change_type not in HYPOTHETICAL_CHANGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported change_type. Valid: {HYPOTHETICAL_CHANGE_TYPES}",
        )

    severity = _SEVERITY_MAP.get(request.change_type, "LOW")
    is_breaking = _BREAKING.get(request.change_type, False)

    # ──── Resolve the simulation target to a graph node ────
    # Graph nodes are tables/views (schema.table), not columns. If the user
    # simulates a column-level change like COLUMN_REMOVED on
    # "schema.table.col", we walk impact from the parent TABLE node because
    # downstream consumers always depend on the table, never on a bare column.
    parts = request.object_identifier.split(".")
    target_name = request.object_identifier
    if request.change_type.startswith("COLUMN_") and len(parts) >= 3:
        target_name = ".".join(parts[:2])  # schema.table

    # Find the node
    with Session(bind=engine) as session:
        nodes = session.execute(
            select(GraphNode).where(GraphNode.snapshot_id == request.snapshot_id)
        ).scalars().all()

    # Single pass over nodes: build the id->name lookup and find the target.
    # Match fallback (n.object_name == target_name) handles cases where the
    # user provides just the table name without a schema prefix.
    node_name_by_id = {}
    target_node_id = None
    for n in nodes:
        full_name = f"{n.schema_name}.{n.object_name}" if n.schema_name else n.object_name
        node_name_by_id[n.node_id] = full_name
        if full_name == target_name or n.object_name == target_name:
            target_node_id = n.node_id

    direct_impacts: List[Dict[str, Any]] = []
    indirect_impacts: List[Dict[str, Any]] = []

    if target_node_id is not None:
        downstream = compute_downstream_impact(
            start_node_id=target_node_id,
            snapshot_id=request.snapshot_id,
        )
        # Convention: depth=1 = immediate dependents (direct), depth>1 =
        # transitive chain (indirect). Useful for UI grouping.
        for item in downstream:
            nid = item["node_id"]
            name = node_name_by_id.get(nid, f"node:{nid}")
            entry = {
                "object_name": name,
                "impact_level": "DOWNSTREAM",
                "depth": item["depth"],
            }
            if item["depth"] == 1:
                direct_impacts.append(entry)
            else:
                indirect_impacts.append(entry)

        # Upstream nodes are NOT affected by removing/altering the target (a
        # change cannot propagate backwards), but they're shown as context so
        # the user understands what feeds into the object being simulated.
        upstream = compute_upstream_impact(
            start_node_id=target_node_id,
            snapshot_id=request.snapshot_id,
        )
        for item in upstream[:10]:  # cap
            nid = item["node_id"]
            name = node_name_by_id.get(nid, f"node:{nid}")
            indirect_impacts.append({
                "object_name": name,
                "impact_level": "UPSTREAM",
                "depth": item["depth"],
            })

    # Query + user count from UsageEvent
    queries_affected = 0
    users_affected = 0
    try:
        from app.usage.usage_models import UsageEvent
        with Session(bind=engine) as session:
            usage_rows = session.execute(select(UsageEvent)).scalars().all()
            # Index usage by BOTH full qualified name ("schema.table") and the
            # short table name — query logs may store either form, and we
            # don't want to miss matches because of a prefix mismatch.
            usage_map = {}
            for u in usage_rows:
                usage_map[u.object_name] = (u.query_count or 0, u.user_count or 0)
                short = u.object_name.split(".")[-1]
                if short not in usage_map:
                    usage_map[short] = (u.query_count or 0, u.user_count or 0)

        # Sum queries/users for the target + all affected objects
        affected_names = {target_name} | {i["object_name"] for i in direct_impacts} | {i["object_name"] for i in indirect_impacts}
        for name in affected_names:
            if name in usage_map:
                q, u = usage_map[name]
                queries_affected += q
                users_affected += u
            else:
                short = name.split(".")[-1]
                if short in usage_map:
                    q, u = usage_map[short]
                    queries_affected += q
                    users_affected += u
    except Exception:
        pass

    # Risk ladder: a breaking change is HIGH if it touches many dependents OR
    # is heavily queried; MEDIUM for any breaking change or moderately-used
    # object; LOW otherwise. Thresholds were calibrated against demo data.
    impact_count = len(direct_impacts) + len(indirect_impacts)
    if is_breaking and (impact_count >= 3 or queries_affected >= 5000):
        risk_level = "HIGH"
    elif is_breaking or impact_count >= 5 or queries_affected >= 1000:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # Build recommendation
    if risk_level == "HIGH":
        recommendation = (
            f"⚠️ HIGH RISK: This change would affect {impact_count} dependent object(s) "
            f"and touch approximately {queries_affected:,} queries run by {users_affected} user(s). "
            f"DO NOT proceed without: (1) notifying all downstream consumers, "
            f"(2) updating dependent views/procedures, (3) running regression tests."
        )
    elif risk_level == "MEDIUM":
        recommendation = (
            f"⚡ MEDIUM RISK: {impact_count} dependent object(s) would be affected. "
            f"~{queries_affected:,} queries touch this object. "
            f"Review dependent code and plan a migration path before applying."
        )
    else:
        recommendation = (
            f"✓ LOW RISK: Minimal impact detected ({impact_count} dependents, "
            f"~{queries_affected:,} queries). Safe to proceed with standard testing."
        )

    return {
        "object_identifier": request.object_identifier,
        "change_type": request.change_type,
        "snapshot_id": request.snapshot_id,
        "is_breaking": is_breaking,
        "severity": severity,
        "direct_impacts": direct_impacts,
        "indirect_impacts": indirect_impacts,
        "queries_affected": queries_affected,
        "users_affected": users_affected,
        "recommendation": recommendation,
        "risk_level": risk_level,
    }
