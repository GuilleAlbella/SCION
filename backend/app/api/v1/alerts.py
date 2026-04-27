from __future__ import annotations

"""Alerts API (v1).

Surfaces recent alerts: breaking changes, high-severity changes,
high-risk reasoning results, etc.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Query, status
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent
from app.metrics.anomaly_detection import (
    detect_anomalies,
    DEFAULT_Z_THRESHOLD,
    MIN_BASELINE_SIZE,
)
from dataclasses import asdict as _asdict


router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertItem(BaseModel):
    id: int
    alert_type: str
    severity: str
    message: str
    object_identifier: str
    timestamp: str
    source: str


class AlertsResponse(BaseModel):
    alerts: List[AlertItem]
    total: int


@router.get("", status_code=status.HTTP_200_OK, response_model=AlertsResponse)
def get_alerts(limit: int = Query(default=50, le=200)) -> Dict[str, Any]:
    """Return recent alerts derived from breaking changes, high severity, and reasoning."""

    alerts: List[Dict[str, Any]] = []
    alert_id = 0

    # Breaking / high-severity changes
    with Session(bind=engine) as session:
        rows = session.execute(
            select(ChangeEvent)
            .where(
                (ChangeEvent.is_breaking == True) | (ChangeEvent.severity == "HIGH")
            )
            .order_by(desc(ChangeEvent.detected_at))
            .limit(limit)
        ).scalars().all()

    for r in rows:
        alert_id += 1
        if r.is_breaking:
            alerts.append({
                "id": alert_id,
                "alert_type": "BREAKING_CHANGE",
                "severity": "HIGH",
                "message": f"Breaking change detected: {r.change_type} on {r.object_identifier}",
                "object_identifier": r.object_identifier,
                "timestamp": r.detected_at.isoformat() if r.detected_at else "",
                "source": f"Diff #{r.snapshot_from}→#{r.snapshot_to}",
            })
        elif r.severity == "HIGH":
            alert_id += 1
            alerts.append({
                "id": alert_id,
                "alert_type": "HIGH_SEVERITY",
                "severity": "HIGH",
                "message": f"High-severity change: {r.change_type} on {r.object_identifier}",
                "object_identifier": r.object_identifier,
                "timestamp": r.detected_at.isoformat() if r.detected_at else "",
                "source": f"Diff #{r.snapshot_from}→#{r.snapshot_to}",
            })

    # High-risk reasoning events
    try:
        from app.taisa.taisa_models import ReasoningEvent
        with Session(bind=engine) as session:
            reasoning_rows = session.execute(
                select(ReasoningEvent)
                .where(ReasoningEvent.risk_level.in_(["HIGH", "CRITICAL"]))
                .order_by(desc(ReasoningEvent.created_at))
                .limit(20)
            ).scalars().all()

        for r in reasoning_rows:
            alert_id += 1
            alerts.append({
                "id": alert_id,
                "alert_type": "HIGH_RISK_REASONING",
                "severity": r.risk_level,
                "message": f"TAISA flagged {r.risk_level} risk: {r.classification}",
                "object_identifier": f"change:{r.change_id}" if r.change_id else "batch",
                "timestamp": r.created_at.isoformat() if r.created_at else "",
                "source": "TAISA Reasoning",
            })
    except Exception:
        pass

    # ── Proactive structural alerts (computed on-demand from the latest snapshot) ──
    try:
        from app.graph.graph_models import GraphNode, GraphEdge
        from app.db.models.snapshot import Snapshot
        with Session(bind=engine) as session:
            latest_snap = session.execute(
                select(Snapshot).order_by(desc(Snapshot.snapshot_id)).limit(1)
            ).scalar_one_or_none()

            if latest_snap:
                snap_id = latest_snap.snapshot_id
                snap_ts = latest_snap.snapshot_time.isoformat() if latest_snap.snapshot_time else ""

                # All nodes and edges in the latest snapshot
                nodes = session.execute(
                    select(GraphNode).where(GraphNode.snapshot_id == snap_id)
                ).scalars().all()
                edges = session.execute(
                    select(GraphEdge).where(GraphEdge.snapshot_id == snap_id)
                ).scalars().all()

                node_ids = {n.node_id for n in nodes}
                node_name_by_id = {n.node_id: f"{n.schema_name}.{n.object_name}" if n.schema_name else n.object_name for n in nodes}

                # ──── Proactive check 1: broken lineage ────
                # An edge pointing to a node that no longer exists in this
                # snapshot means something was deleted without cleaning up its
                # references — a silent data quality problem worth surfacing.
                broken = []
                for e in edges:
                    if e.source_node_id not in node_ids:
                        broken.append(("source", e.source_node_id, e.target_node_id))
                    elif e.target_node_id not in node_ids:
                        broken.append(("target", e.source_node_id, e.target_node_id))

                for side, src, tgt in broken[:15]:
                    alert_id += 1
                    missing = src if side == "source" else tgt
                    alerts.append({
                        "id": alert_id,
                        "alert_type": "BROKEN_LINEAGE",
                        "severity": "HIGH",
                        "message": f"Broken lineage: edge references missing node (id={missing})",
                        "object_identifier": node_name_by_id.get(tgt if side == "source" else src, f"node:{missing}"),
                        "timestamp": snap_ts,
                        "source": f"Snapshot #{snap_id}",
                    })

                # ──── Proactive check 2: orphan objects ────
                # A table with no incoming or outgoing edges is either dead
                # code or a lineage gap. Schemas/databases are excluded
                # because they're container nodes that need no direct edges.
                connected_nodes = set()
                for e in edges:
                    connected_nodes.add(e.source_node_id)
                    connected_nodes.add(e.target_node_id)

                orphans = [
                    n for n in nodes
                    if n.node_id not in connected_nodes
                    and n.object_type not in ("SCHEMA", "DATABASE")
                ]
                for n in orphans[:10]:
                    alert_id += 1
                    alerts.append({
                        "id": alert_id,
                        "alert_type": "ORPHAN_OBJECT",
                        "severity": "MEDIUM",
                        "message": f"Orphan object — no upstream or downstream dependencies detected",
                        "object_identifier": node_name_by_id.get(n.node_id, n.object_name),
                        "timestamp": snap_ts,
                        "source": f"Snapshot #{snap_id}",
                    })

                # ──── Proactive check 3: hub-node changes ────
                # A hub (>=5 total edges) concentrates risk — changing one
                # propagates everywhere. Cross-referencing recent changes
                # against the hub list flags these for extra scrutiny.
                hub_nodes = [
                    n for n in nodes
                    if (n.node_metadata or {}).get("is_hub")
                ]
                hub_names = {node_name_by_id.get(h.node_id, h.object_name) for h in hub_nodes}

                with Session(bind=engine) as s2:
                    recent_hub_changes = s2.execute(
                        select(ChangeEvent)
                        .where(ChangeEvent.snapshot_to == snap_id)
                        .order_by(desc(ChangeEvent.detected_at))
                    ).scalars().all()

                for c in recent_hub_changes:
                    if c.object_identifier in hub_names:
                        alert_id += 1
                        alerts.append({
                            "id": alert_id,
                            "alert_type": "HUB_CHANGED",
                            "severity": "HIGH",
                            "message": f"Hub node changed — high-connectivity object was modified",
                            "object_identifier": c.object_identifier,
                            "timestamp": c.detected_at.isoformat() if c.detected_at else snap_ts,
                            "source": f"Diff #{c.snapshot_from}→#{c.snapshot_to}",
                        })
                        if len([a for a in alerts if a["alert_type"] == "HUB_CHANGED"]) >= 10:
                            break
    except Exception:
        pass

    # Sort by timestamp desc
    alerts.sort(key=lambda a: a["timestamp"], reverse=True)

    return {
        "alerts": alerts[:limit],
        "total": len(alerts),
    }


# ──── Statistical anomaly detection (v1.07 data-science pack) ────
# Kept as a dedicated endpoint rather than folded into /alerts so the UI
# can render a visually distinct "statistical anomalies" card (z-scores,
# expected vs observed) — the generic /alerts schema has no room for
# those fields.

@router.get("/anomalies", status_code=status.HTTP_200_OK)
def get_anomalies(
    z_threshold: float = DEFAULT_Z_THRESHOLD,
    min_baseline: int = MIN_BASELINE_SIZE,
) -> Dict[str, Any]:
    """Per-(schema, snapshot) change-volume anomalies flagged by z-score.

    Uses leave-one-out mean/stdev over the schema's own history — so a
    spike can't hide itself inside its own baseline. Returns the full
    list sorted by |z-score| desc.
    """
    records = detect_anomalies(
        z_threshold=z_threshold,
        min_baseline=min_baseline,
    )
    return {
        "z_threshold": z_threshold,
        "min_baseline": min_baseline,
        "total": len(records),
        "anomalies": [_asdict(r) for r in records],
    }
