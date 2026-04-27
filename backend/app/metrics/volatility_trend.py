from __future__ import annotations

"""Rolling volatility trend per schema/domain.

Feature #3 of the v1.07 data-science pack. Extends the point-in-time
`structural_volatility_index` (already in `intelligence_metrics.py`) with
a **time series** view, so governance dashboards can show trajectories
rather than single values.

For each schema we compute, at every snapshot:

    volatility(schema, t) = unique_objects_changed(schema, last N snapshots ending at t)
                            / total_objects(schema, t)

This is the fraction of the schema's surface area that "moved" within
the rolling window. Values close to 0 = stable; values close to 1 =
the entire schema is churning.

We then return the series per schema along with a **delta** comparing the
current window vs the immediately prior window (i.e. discrete derivative),
which is the single most actionable signal for a CDO: "my governance
program is working" == delta trending down.
"""

from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.diff.diff_models import ChangeEvent


# Default rolling window (in snapshots). Tuned for demo-scale data where
# we only have ~10 snapshots; in production with daily snapshots this
# would be 7–14 and would represent weekly cadence.
DEFAULT_WINDOW = 3


@dataclass
class VolatilityPoint:
    """One sample in a volatility time series."""
    snapshot_id: int
    volatility: float          # [0, 1]
    objects_changed: int       # numerator
    objects_total: int         # denominator


@dataclass
class SchemaVolatilityTrend:
    """Per-schema rolling volatility series with current/prior delta."""
    schema_name: str
    window: int
    series: List[VolatilityPoint]
    current_volatility: float
    prior_volatility: float
    delta: float               # current - prior (positive = worsening)
    delta_pct: float           # same, expressed as % of prior
    trend: str                 # "worsening" / "improving" / "stable"


def _classify_trend(delta_pct: float, epsilon: float = 5.0) -> str:
    """Label a percentage delta as worsening / improving / stable.

    The epsilon band (±5%) avoids labelling rounding noise as a trend.
    Sign convention: delta > 0 means volatility went UP = WORSE.
    """
    if delta_pct > epsilon:
        return "worsening"
    if delta_pct < -epsilon:
        return "improving"
    return "stable"


def compute_schema_volatility_trend(
    window: int = DEFAULT_WINDOW,
) -> List[SchemaVolatilityTrend]:
    """Return rolling volatility per schema across all snapshots.

    Algorithm:
      1. Load all snapshots in order + their schema→table counts.
      2. Load all change events indexed by (schema, snapshot_to).
      3. For each schema × snapshot_t, compute:
           numerator   = distinct objects in this schema that changed
                         in snapshots (t-window+1 .. t)
           denominator = # of objects in this schema AT snapshot t
           volatility  = num / den
      4. Emit the full series plus the delta between the last and
         second-to-last points.
    """
    # ── 1. Snapshot order + per-schema object counts per snapshot ──
    with Session(bind=engine) as session:
        schema_rows = session.execute(
            select(
                SchemaSnapshot.snapshot_id,
                SchemaSnapshot.schema_id,
                SchemaSnapshot.schema_name,
            )
        ).all()
        table_rows = session.execute(
            select(TableSnapshot.schema_id)
        ).all()

    # Build schema_id -> schema_name and (snapshot, schema) -> count
    counts: Dict[Tuple[int, str], int] = {}
    schema_id_to_snap: Dict[int, Tuple[int, str]] = {}
    for snap_id, schema_id, schema_name in schema_rows:
        schema_id_to_snap[schema_id] = (snap_id, schema_name)

    for (schema_id,) in table_rows:
        if schema_id in schema_id_to_snap:
            snap_id, schema_name = schema_id_to_snap[schema_id]
            key = (snap_id, schema_name)
            counts[key] = counts.get(key, 0) + 1

    # All snapshot ids, ordered. Schema lives inside snapshots, so we take
    # the universe of snapshot_ids from the schema_snapshot table.
    all_snapshots = sorted({snap_id for snap_id, _, _ in schema_rows})
    if not all_snapshots:
        return []

    # ── 2. change_event indexed by (schema, snapshot_to) ──
    # We dedupe objects within a snapshot so a table with many column
    # changes still counts as one "object changed", matching the intuition
    # of "surface area touched".
    with Session(bind=engine) as session:
        change_rows = session.execute(
            select(
                ChangeEvent.snapshot_to,
                ChangeEvent.object_identifier,
                ChangeEvent.object_type,
            )
        ).all()

    changed_by: Dict[Tuple[str, int], set[str]] = {}
    for snap_to, identifier, otype in change_rows:
        schema = (identifier or "").split(".", 1)[0] or "(unknown)"
        parent = _parent_object(identifier, otype)
        if not parent:
            continue
        changed_by.setdefault((schema, snap_to), set()).add(parent)

    # ── 3. Build the per-schema series ──
    all_schemas = sorted({schema_name for _, _, schema_name in schema_rows})
    trends: List[SchemaVolatilityTrend] = []

    for schema in all_schemas:
        series: List[VolatilityPoint] = []
        for i, t in enumerate(all_snapshots):
            window_snaps = all_snapshots[max(0, i - window + 1): i + 1]
            changed = set()
            for ws in window_snaps:
                changed.update(changed_by.get((schema, ws), set()))

            total = counts.get((t, schema), 0)
            vol = (len(changed) / total) if total > 0 else 0.0
            series.append(VolatilityPoint(
                snapshot_id=t,
                volatility=round(vol, 4),
                objects_changed=len(changed),
                objects_total=total,
            ))

        # ── 4. Delta between the most recent and its predecessor ──
        current = series[-1].volatility if series else 0.0
        prior = series[-2].volatility if len(series) >= 2 else current
        delta = current - prior
        delta_pct = (delta / prior * 100.0) if prior > 0 else (100.0 if delta > 0 else 0.0)

        trends.append(SchemaVolatilityTrend(
            schema_name=schema,
            window=window,
            series=series,
            current_volatility=round(current, 4),
            prior_volatility=round(prior, 4),
            delta=round(delta, 4),
            delta_pct=round(delta_pct, 2),
            trend=_classify_trend(delta_pct),
        ))

    # Rank: worsening + high current first (= most worth attention)
    trends.sort(
        key=lambda t: (
            0 if t.trend == "worsening" else 1 if t.trend == "stable" else 2,
            -t.current_volatility,
        )
    )
    return trends


def _parent_object(identifier: str, object_type: str) -> str | None:
    """Collapse COLUMN changes up to their parent table so co-change /
    volatility operate at a consistent "object" granularity.
    """
    if not identifier:
        return None
    parts = identifier.split(".")
    if object_type == "COLUMN" and len(parts) >= 3:
        return ".".join(parts[:2])
    return identifier


def volatility_trend_as_dicts(**kwargs) -> List[Dict]:
    """Convenience wrapper that serialises the dataclasses to nested dicts."""
    out = []
    for t in compute_schema_volatility_trend(**kwargs):
        d = asdict(t)
        # asdict handles the nested dataclasses automatically
        out.append(d)
    return out
