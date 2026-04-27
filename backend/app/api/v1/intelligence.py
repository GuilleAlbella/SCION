from __future__ import annotations

"""Intelligence Metrics API (v1) — Governance scorecards and indices."""

from dataclasses import asdict
from typing import Any, Dict, List

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.metrics.intelligence_metrics import (
    governance_scorecard,
    domain_risk_index,
    structural_volatility_index,
    change_density,
    stability_trend,
)
from app.metrics.cochange import mine_cochange_pairs, DEFAULT_MIN_LIFT, DEFAULT_MIN_PAIR_SUPPORT
from app.metrics.volatility_trend import compute_schema_volatility_trend, DEFAULT_WINDOW
from dataclasses import asdict as _asdict


router = APIRouter(prefix="/intelligence", tags=["intelligence"])

# All endpoints in this module are thin pass-throughs over app.metrics —
# computation lives there so the metrics can be reused by reports, alerts,
# and TAISA context builders without going through HTTP.


@router.get("/scorecard/{snapshot_id}", status_code=status.HTTP_200_OK)
def get_scorecard(snapshot_id: int) -> Dict[str, Any]:
    """Executive governance scorecard for a snapshot."""
    sc = governance_scorecard(snapshot_id)
    return sc.to_dict()


@router.get("/domain-risk/{snapshot_id}", status_code=status.HTTP_200_OK)
def get_domain_risk(snapshot_id: int) -> Dict[str, Any]:
    """Risk index per schema/domain."""
    risks = domain_risk_index(snapshot_id)
    return {
        "snapshot_id": snapshot_id,
        "domains": [asdict(r) for r in risks],
        "total": len(risks),
    }


@router.get("/volatility", status_code=status.HTTP_200_OK)
def get_volatility() -> Dict[str, Any]:
    """System-wide volatility index."""
    vol = structural_volatility_index()
    return {"volatility_index": vol}


@router.get("/density", status_code=status.HTTP_200_OK)
def get_density(snapshot_from: int, snapshot_to: int) -> Dict[str, Any]:
    """Change density between two snapshots."""
    d = change_density(snapshot_from, snapshot_to)
    return {
        "snapshot_from": snapshot_from,
        "snapshot_to": snapshot_to,
        "density": d,
    }


@router.get("/stability/{object_name:path}", status_code=status.HTTP_200_OK)
def get_stability(object_name: str) -> Dict[str, Any]:
    """Stability trend for a specific object."""
    record = stability_trend(object_name)
    return asdict(record)


# ──── v1.07 Data-science pack ────
# These three endpoints expose statistical/data-mining analyses over the
# change history: co-change association rules and rolling volatility
# trend. The anomaly detector is exposed from the alerts router (it's
# operationally an alert source).

@router.get("/cochange", status_code=status.HTTP_200_OK)
def get_cochange(
    min_lift: float = DEFAULT_MIN_LIFT,
    min_pair_support: int = DEFAULT_MIN_PAIR_SUPPORT,
    top_n: int = 50,
) -> Dict[str, Any]:
    """Top-N directional co-change association rules across the history.

    Returns rules (object_a, object_b) with support/confidence/lift, surfaced
    from the `change_event` log via Apriori-style pairwise mining. A `lift`
    above 1 indicates historical coupling beyond chance.
    """
    pairs = mine_cochange_pairs(
        min_pair_support=min_pair_support,
        min_lift=min_lift,
        top_n=top_n,
    )
    return {
        "total": len(pairs),
        "min_lift": min_lift,
        "min_pair_support": min_pair_support,
        "pairs": [_asdict(p) for p in pairs],
    }


@router.get("/volatility-trend", status_code=status.HTTP_200_OK)
def get_volatility_trend(window: int = DEFAULT_WINDOW) -> Dict[str, Any]:
    """Rolling volatility per schema with a time-series and current/prior delta.

    For each schema, returns a series of (snapshot_id, volatility) samples
    plus the immediate delta vs the prior window and a `trend` label
    (worsening / stable / improving). Governance dashboards can render the
    series as a sparkline and use the delta as a single actionable KPI.
    """
    trends = compute_schema_volatility_trend(window=window)
    return {
        "window": window,
        "total": len(trends),
        "trends": [_asdict(t) for t in trends],
    }
