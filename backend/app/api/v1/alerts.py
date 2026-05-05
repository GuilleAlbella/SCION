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

    # ──── Proactive structural alerts (read from pre-computed table) ────
    # Until v1.19, this block loaded every graph_node + graph_edge for
    # the latest snapshot and ran the 3 checks inline on each request —
    # 337k+ rows + Python walks per click. The work has moved to
    # ``run_post_ingest_pipeline`` (writes into ``proactive_alert``),
    # so the endpoint just reads indexed rows. Lazy fallback: if no
    # rows exist for the latest snapshot (pre-v1.19 imports), compute
    # on the fly so /alerts isn't empty for legacy data.
    try:
        from app.db.models.snapshot import Snapshot
        from app.graph.impact_models import ProactiveAlert

        with Session(bind=engine) as session:
            latest_snap = session.execute(
                select(Snapshot).order_by(desc(Snapshot.snapshot_id)).limit(1)
            ).scalar_one_or_none()

            if latest_snap is not None:
                snap_id = latest_snap.snapshot_id
                snap_ts = (
                    latest_snap.snapshot_time.isoformat()
                    if latest_snap.snapshot_time
                    else ""
                )

                pre_rows = session.execute(
                    select(ProactiveAlert)
                    .where(ProactiveAlert.snapshot_id == snap_id)
                    .order_by(ProactiveAlert.computed_at)
                ).scalars().all()

                # Lazy backfill for snapshots ingested under earlier
                # versions. We run the computation once and re-read.
                # Bounded by the same caps the helper applies.
                if not pre_rows:
                    try:
                        from app.graph.proactive_alerts import (
                            persist_proactive_alerts,
                        )
                        persist_proactive_alerts(snap_id)
                        pre_rows = session.execute(
                            select(ProactiveAlert)
                            .where(ProactiveAlert.snapshot_id == snap_id)
                            .order_by(ProactiveAlert.computed_at)
                        ).scalars().all()
                    except Exception:
                        # Keep the endpoint usable even if backfill
                        # fails — the change-event-based alerts above
                        # are independent and already populated.
                        pre_rows = []

                for r in pre_rows:
                    alert_id += 1
                    alerts.append({
                        "id": alert_id,
                        "alert_type": r.alert_type,
                        "severity": r.severity,
                        "message": r.message,
                        "object_identifier": r.object_identifier,
                        "timestamp": (
                            r.computed_at.isoformat() if r.computed_at else snap_ts
                        ),
                        "source": f"Snapshot #{snap_id}",
                    })
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
