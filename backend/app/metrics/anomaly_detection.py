from __future__ import annotations

"""Statistical anomaly detection over the change_event history.

Feature #1 of the v1.07 data-science pack. The idea is simple: each
`schema` has a *normal* cadence of structural change (e.g. `reporting`
averages 1.2 changes per snapshot, `staging` averages 0.3). When a new
snapshot produces a volume that deviates significantly from that baseline
— measured by z-score against the schema's own historical distribution —
we surface it as an anomaly.

This is **classical statistical process control**, not machine learning:
- Zero training required. The baseline IS the history.
- Explainable (we return mean, std, z-score, observed count).
- Cheap to compute — one pass over `change_event`.

The complementary value is that it catches *patterns* that per-change
rules miss: every change in isolation may be legitimate, but 6 changes
landing in one week on a schema that normally gets 0.5 is a signal
(unannounced refactor, migration-in-flight, team churn).
"""

import math
import statistics
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent


# Minimum snapshots with data we require before trusting a baseline.
# Below this, z-scores are unstable and we abstain from flagging anything.
MIN_BASELINE_SIZE = 3

# Threshold above which a z-score is considered anomalous.
# 2.0 ≈ 95th percentile (two-sided), standard SPC convention.
DEFAULT_Z_THRESHOLD = 2.0


@dataclass
class AnomalyRecord:
    """One detected anomaly for a (schema, snapshot) pair."""
    schema_name: str
    snapshot_id: int
    observed: int          # cambios en esta ventana
    expected: float        # media histórica
    std_dev: float         # desvío estándar histórico
    z_score: float         # (observed - expected) / std_dev
    baseline_size: int     # # snapshots usados para baseline
    severity: str          # LOW / MEDIUM / HIGH


def _severity_for_z(z: float) -> str:
    """Bucket a z-score into the same severity language the rest of SCION uses.

    The thresholds are the SPC-standard ones (2σ, 3σ), chosen deliberately
    so that `HIGH` aligns with "would be flagged by a control chart".
    """
    az = abs(z)
    if az >= 3.0:
        return "HIGH"
    if az >= 2.0:
        return "MEDIUM"
    return "LOW"


def detect_anomalies(
    z_threshold: float = DEFAULT_Z_THRESHOLD,
    min_baseline: int = MIN_BASELINE_SIZE,
) -> List[AnomalyRecord]:
    """Compute per-(schema, snapshot) anomalies across the full history.

    Algorithm:
      1. Group every `change_event` row by `(schema, snapshot_to)`.
      2. For each schema, build a distribution of "changes per snapshot"
         across its entire history.
      3. Compute mean + std over the baseline (everything EXCEPT the
         snapshot being evaluated — leave-one-out, so a single outlier
         doesn't hide itself by inflating its own expected value).
      4. Flag `(schema, snapshot)` with |z| >= `z_threshold`.

    Returns anomalies sorted by absolute z-score descending.
    """
    # ── 1. Load all change events with their schema prefix ──
    per_schema_snapshot: Dict[str, Dict[int, int]] = {}
    all_snapshots: set[int] = set()
    with Session(bind=engine) as session:
        rows = session.execute(
            select(
                ChangeEvent.object_identifier,
                ChangeEvent.snapshot_to,
            )
        ).all()

    for identifier, snap_to in rows:
        schema = (identifier or "").split(".", 1)[0] or "(unknown)"
        per_schema_snapshot.setdefault(schema, {})
        per_schema_snapshot[schema][snap_to] = per_schema_snapshot[schema].get(snap_to, 0) + 1
        all_snapshots.add(snap_to)

    # ── 2. For each schema, compute leave-one-out z-score per snapshot ──
    results: List[AnomalyRecord] = []
    for schema, counts in per_schema_snapshot.items():
        # Fill zeros for snapshots where this schema had no changes at all —
        # absence IS part of its distribution.
        full = {snap: counts.get(snap, 0) for snap in all_snapshots}

        if len(full) < min_baseline + 1:
            continue  # not enough data to compute a stable baseline

        for snap_id, observed in full.items():
            baseline = [v for s, v in full.items() if s != snap_id]
            if len(baseline) < min_baseline:
                continue

            mean = statistics.fmean(baseline)
            stdev = statistics.pstdev(baseline) if len(baseline) > 1 else 0.0

            # Degenerate case: all-zero baseline. Any positive observation
            # is implicitly anomalous, but we can't compute z-score. Use a
            # conservative synthetic z of 3.0 to still surface it.
            if stdev == 0:
                if observed == mean:
                    continue
                z = 3.0 if observed > mean else -3.0
            else:
                z = (observed - mean) / stdev

            if abs(z) < z_threshold:
                continue

            results.append(AnomalyRecord(
                schema_name=schema,
                snapshot_id=snap_id,
                observed=observed,
                expected=round(mean, 2),
                std_dev=round(stdev, 2),
                z_score=round(z, 2),
                baseline_size=len(baseline),
                severity=_severity_for_z(z),
            ))

    # Most-anomalous first (by absolute deviation, not raw direction).
    results.sort(key=lambda r: abs(r.z_score), reverse=True)
    return results


def anomalies_as_dicts(**kwargs) -> List[Dict]:
    """Convenience wrapper for API/JSON consumers."""
    return [asdict(r) for r in detect_anomalies(**kwargs)]
