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

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.schema_snapshot import SchemaSnapshot
from app.diff.diff_models import ChangeEvent


# Default rolling window (in snapshots). Tuned for demo-scale data where
# we only have ~10 snapshots; in production with daily snapshots this
# would be 7â€“14 and would represent weekly cadence.
DEFAULT_WINDOW = 3

# Cap on history depth (most recent N snapshots scanned). Same motivation
# as the cochange cap: at Transcend scale the un-capped scan over
# change_event made the Intelligence page hang. 20 covers a few months
# of weekly-import history, which is plenty for a "recent trajectory"
# view; older data wouldn't change the trend anyway.
DEFAULT_MAX_HISTORY_SNAPSHOTS = 20


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

    The epsilon band (Â±5%) avoids labelling rounding noise as a trend.
    Sign convention: delta > 0 means volatility went UP = WORSE.
    """
    if delta_pct > epsilon:
        return "worsening"
    if delta_pct < -epsilon:
        return "improving"
    return "stable"


def compute_schema_volatility_trend(
    window: int = DEFAULT_WINDOW,
    max_history_snapshots: int = DEFAULT_MAX_HISTORY_SNAPSHOTS,
) -> List[SchemaVolatilityTrend]:
    """Return rolling volatility per schema across the recent history.

    Algorithm:
      1. Identify the ``max_history_snapshots`` most recent snapshots â€”
         this is the universe scanned for changes. Anything older is
         excluded so the function stays bounded at production scale.
      2. Load schemaâ†’table counts for those snapshots.
      3. Load change events for those snapshots, indexed by
         (schema, snapshot_to).
      4. For each schema Ã— snapshot_t in scope, compute:
           numerator   = distinct objects in this schema that changed
                         in snapshots (t-window+1 .. t)
           denominator = # of objects in this schema AT snapshot t
           volatility  = num / den
      5. Emit the per-schema series plus the delta between the last and
         second-to-last points.
    """
    # â”€â”€ 1. Snapshot order + per-schema object counts per snapshot â”€â”€
    # Restricted to the most-recent ``max_history_snapshots`` so this
    # never tries to walk every historical snapshot at Transcend scale.
    #
    # Performance note (v1.21.11): the original code loaded all
    # schema_snapshot rows and then ALL table_snapshot rows via a large
    # IN-clause (up to 37 k schema_ids), causing multi-second latency on
    # production. Replaced with a single JOIN-based aggregate per snapshot
    # so the work stays server-side and benefits from the existing indexes.
    with Session(engine) as session:
        recent_snapshot_ids = [
            int(s) for s in session.execute(
                select(SchemaSnapshot.snapshot_id)
                .distinct()
                .order_by(SchemaSnapshot.snapshot_id.desc())
                .limit(max_history_snapshots)
            ).scalars().all()
        ]
        if not recent_snapshot_ids:
            return []

        snap_id_list = ",".join(str(s) for s in recent_snapshot_ids)

        # (snapshot_id, schema_name, table_count) â€” one row per schemaÃ—snap.
        # JOIN keeps all work server-side; no large IN-clause over schema_ids.
        count_rows = session.execute(text(f"""
            SELECT ss.snapshot_id, ss.schema_name, COUNT(ts.table_id) AS table_count
            FROM schema_snapshot ss
            LEFT JOIN table_snapshot ts ON ts.schema_id = ss.schema_id
            WHERE ss.snapshot_id IN ({snap_id_list})
            GROUP BY ss.snapshot_id, ss.schema_name
        """)).fetchall()

        # (snapshot_to, schema_name, objects_changed) aggregate â€” avoids
        # loading all 1.86 M change_event rows into Python.
        # COLUMN changes are collapsed to their parent table using inline
        # SUBSTR so the numerator counts "tables touched", not raw columns.
        #
        #   p1 = position of the first dot
        #   p2 = p1 + position of the first dot in the remainder
        #        (i.e. position of the second dot in the full identifier)
        #
        # If object_type = COLUMN and a second dot exists â†’ return
        # SCHEMA.TABLE; otherwise return the full identifier.
        change_agg = session.execute(text(f"""
            SELECT
                snapshot_to,
                SUBSTR(object_identifier, 1,
                       INSTR(object_identifier || '.', '.') - 1) AS schema_name,
                COUNT(DISTINCT
                    CASE
                        WHEN object_type = 'COLUMN'
                             AND INSTR(
                                    SUBSTR(object_identifier,
                                           INSTR(object_identifier, '.') + 1),
                                    '.') > 0
                        THEN SUBSTR(object_identifier, 1,
                                INSTR(object_identifier, '.') +
                                INSTR(SUBSTR(object_identifier,
                                             INSTR(object_identifier, '.') + 1),
                                      '.'))
                        ELSE object_identifier
                    END
                ) AS objects_changed
            FROM change_event
            WHERE snapshot_to IN ({snap_id_list})
            GROUP BY snapshot_to, schema_name
        """)).fetchall()

    # Build (snapshot_id, schema_name) -> table_count
    counts: Dict[Tuple[int, str], int] = {
        (int(r[0]), r[1]): int(r[2]) for r in count_rows
    }

    # All snapshot ids present in schema_snapshot, ordered ascending.
    all_snapshots = sorted({int(r[0]) for r in count_rows})
    if not all_snapshots:
        return []

    # Build (schema_name, snapshot_to) -> distinct_objects_changed
    changed_by: Dict[Tuple[str, int], int] = {
        (r[1], int(r[0])): int(r[2]) for r in change_agg
    }

    # â”€â”€ 3. Build the per-schema series â”€â”€
    all_schemas = sorted({r[1] for r in count_rows})
    trends: List[SchemaVolatilityTrend] = []

    for schema in all_schemas:
        series: List[VolatilityPoint] = []
        for i, t in enumerate(all_snapshots):
            # Sum distinct objects changed across the rolling window.
            # Note: the SQL aggregate already dedupes within each snapshot_to;
            # across the window we sum the per-snapshot counts (conservative
            # over-estimate if the same table changed in multiple window snaps,
            # but acceptable for a trend indicator).
            window_snaps = all_snapshots[max(0, i - window + 1): i + 1]
            n_changed = sum(changed_by.get((schema, ws), 0) for ws in window_snaps)

            total = counts.get((t, schema), 0)
            vol = (n_changed / total) if total > 0 else 0.0
            series.append(VolatilityPoint(
                snapshot_id=t,
                volatility=round(vol, 4),
                objects_changed=n_changed,
                objects_total=total,
            ))

        # â”€â”€ 4. Delta between the most recent and its predecessor â”€â”€
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
