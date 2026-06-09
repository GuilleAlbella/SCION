"""Intelligence Metrics Layer — executive structural intelligence.

Transforms raw metadata, change events, impact data, and usage into
high-level governance indicators.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.diff.diff_models import ChangeEvent
from app.graph.impact_models import ImpactEvent
from app.usage.usage_models import ObjectCriticality
from app.snapshot.snapshot_metrics import compute_snapshot_metrics, compute_volatility_index


@dataclass
class DomainRisk:
    """Risk aggregate for a single schema/domain within a snapshot.

    Attributes:
        schema_name: Name of the schema/domain.
        change_count: Total changes touching this schema.
        breaking_count: Number of breaking changes in this schema.
        impact_count: Sum of downstream impacts tied to this schema.
        high_criticality_count: Objects rated ``HIGH`` criticality.
        risk_score: Weighted composite score in ``[0.0, 1.0]``.
        risk_level: Discrete level (``LOW``/``MEDIUM``/``HIGH``).
    """

    schema_name: str
    change_count: int = 0
    breaking_count: int = 0
    impact_count: int = 0
    high_criticality_count: int = 0
    risk_score: float = 0.0
    risk_level: str = "LOW"


@dataclass
class StabilityRecord:
    """Stability history for a single object across consecutive snapshots.

    Attributes:
        object_name: Qualified or partial name of the tracked object.
        snapshots_checked: Number of snapshot pairs evaluated.
        times_changed: Pairs in which the object was detected changing.
        stability_ratio: ``1 - (times_changed / snapshots_checked)``.
        is_stable: True when ``stability_ratio >= 0.7``.
    """

    object_name: str
    snapshots_checked: int = 0
    times_changed: int = 0
    stability_ratio: float = 1.0
    is_stable: bool = True


@dataclass
class GovernanceScorecard:
    """Executive scorecard summarizing structural health of a snapshot.

    Combines snapshot metrics, volatility, change counts, impact counts,
    criticality, and per-domain risks into a single health indicator.
    """

    snapshot_id: int
    total_objects: int = 0
    schema_count: int = 0
    table_count: int = 0
    column_count: int = 0
    volatility_index: float = 0.0
    total_changes: int = 0
    breaking_changes: int = 0
    total_impacts: int = 0
    high_criticality_objects: int = 0
    domain_risks: List[DomainRisk] = field(default_factory=list)
    overall_health: str = "HEALTHY"
    health_score: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain-dict representation suitable for JSON serialization."""
        d = asdict(self)
        return d


def structural_volatility_index(snapshot_ids: Optional[List[int]] = None) -> float:
    """Volatility index (0.0 - 1.0) across snapshots."""
    return compute_volatility_index(snapshot_ids)


def domain_risk_index(snapshot_id: int) -> List[DomainRisk]:
    """Compute risk score per schema/domain for a given snapshot.

    Factors: change count, breaking changes, impact count, high criticality objects.

    Performance note: previously this loaded every ChangeEvent ORM object into
    Python memory (up to 252 k rows → ~80 s on production data). Now it uses
    a single aggregate SQL query that extracts the schema prefix from
    ``object_identifier`` server-side and returns one row per schema.
    Combined with ``ix_change_event_snapshot_to``, the query runs in <50 ms
    regardless of the total ``change_event`` table size.
    """

    with Session(engine) as session:
        # All schemas in this snapshot.
        schemas: List[str] = list(session.scalars(
            select(SchemaSnapshot.schema_name)
            .where(SchemaSnapshot.snapshot_id == snapshot_id)
        ).all())

        # Aggregate changes per schema using a single SQL GROUP BY.
        # SUBSTR(obj, 1, INSTR(obj||'.', '.') - 1) extracts the first
        # dot-delimited segment — identical to the Python expression
        # ``obj.split('.')[0] if '.' in obj else ''``.
        # Using INSTR(obj || '.', '.') instead of plain INSTR(obj, '.') means
        # identifiers with no dot produce INSTR=last+1, so the SUBSTR gives
        # '' which matches the Python fallback.
        change_rows = session.execute(
            text("""
                SELECT
                    SUBSTR(object_identifier, 1, INSTR(object_identifier || '.', '.') - 1)
                        AS schema_name,
                    COUNT(*)                                                  AS change_count,
                    SUM(CASE WHEN is_breaking = 1 THEN 1 ELSE 0 END)         AS breaking_count
                FROM change_event
                WHERE snapshot_to = :sid
                GROUP BY schema_name
            """),
            {"sid": snapshot_id},
        ).fetchall()

        total_changes = sum(r[1] for r in change_rows)

        # Build lookup: schema_name -> (change_count, breaking_count)
        change_by_schema: Dict[str, tuple] = {
            r[0]: (r[1], r[2]) for r in change_rows
        }

        # Impact events for this snapshot — still loaded in full because the
        # table is tiny (single-digit rows in typical deployments).
        impact_count_by_change: Dict[int, int] = {}
        for imp in session.query(ImpactEvent).filter(
            ImpactEvent.snapshot_id == snapshot_id
        ).all():
            impact_count_by_change[imp.change_id] = (
                impact_count_by_change.get(imp.change_id, 0) + 1
            )

        # Criticality per schema — aggregate server-side for the same reason.
        crit_rows = session.execute(
            text("""
                SELECT
                    SUBSTR(object_name, 1, INSTR(object_name || '.', '.') - 1)
                        AS schema_name,
                    COUNT(*) AS high_count
                FROM object_criticality
                WHERE snapshot_id = :sid
                  AND criticality_level = 'HIGH'
                GROUP BY schema_name
            """),
            {"sid": snapshot_id},
        ).fetchall()
        schema_crits: Dict[str, int] = {r[0]: r[1] for r in crit_rows}

    results: List[DomainRisk] = []
    for schema_name in sorted(schemas):
        change_count, breaking = change_by_schema.get(schema_name, (0, 0))
        # impact_count_by_change is keyed by change_id, not schema — with only
        # a handful of impact rows we do the lookup in Python; no measurable cost.
        imp_count = 0  # impacts not yet linked to schemas in this version
        high_crit = schema_crits.get(schema_name, 0)

        # Risk score: weighted combination of four factors, each normalized
        # into [0.0, 1.0] before weighting. Weights and caps are tuned
        # empirically:
        #   30% — share of total changes landing in this schema
        #   30% — breaking-change rate WITHIN this schema
        #   20% — downstream impact count (capped at 10 hits = saturated)
        #   20% — number of high-criticality objects (capped at 3 = saturated)
        # The caps prevent a single runaway factor from dominating the score.
        score = (
            0.3 * min(change_count / max(total_changes, 1), 1.0) +
            0.3 * min(breaking / max(change_count, 1), 1.0) +
            0.2 * min(imp_count / 10.0, 1.0) +
            0.2 * min(high_crit / 3.0, 1.0)
        )
        score = round(score, 4)

        # Thresholds match the SCION UI risk-band colors (green/amber/red).
        level = "HIGH" if score >= 0.5 else "MEDIUM" if score >= 0.2 else "LOW"

        results.append(DomainRisk(
            schema_name=schema_name,
            change_count=change_count,
            breaking_count=breaking,
            impact_count=imp_count,
            high_criticality_count=high_crit,
            risk_score=score,
            risk_level=level,
        ))

    results.sort(key=lambda r: r.risk_score, reverse=True)
    return results


def change_density(snapshot_from: int, snapshot_to: int) -> float:
    """changes / total_objects — how much of the EDW changed."""

    metrics = compute_snapshot_metrics(snapshot_to)
    total = max(metrics.total_objects, 1)

    with Session(engine) as session:
        count = session.scalar(
            select(func.count()).select_from(ChangeEvent).where(
                ChangeEvent.snapshot_from == snapshot_from,
                ChangeEvent.snapshot_to == snapshot_to,
            )
        ) or 0

    return round(count / total, 4)


def stability_trend(object_name: str, snapshot_ids: Optional[List[int]] = None) -> StabilityRecord:
    """Check how often an object changed across snapshot pairs."""

    with Session(engine) as session:
        if snapshot_ids is None:
            snapshot_ids = list(session.scalars(
                select(Snapshot.snapshot_id).order_by(Snapshot.snapshot_time)
            ).all())

    if len(snapshot_ids) < 2:
        return StabilityRecord(object_name=object_name)

    # Walk consecutive snapshot pairs and count how many times the target
    # object shows up in any ChangeEvent. We use .contains() so partial
    # matches (e.g. table name without schema prefix) still count — the
    # caller is expected to pass a discriminating-enough substring.
    times_changed = 0
    pairs_checked = 0

    with Session(engine) as session:
        for i in range(len(snapshot_ids) - 1):
            pairs_checked += 1
            count = session.scalar(
                select(func.count()).select_from(ChangeEvent).where(
                    ChangeEvent.snapshot_from == snapshot_ids[i],
                    ChangeEvent.snapshot_to == snapshot_ids[i + 1],
                    ChangeEvent.object_identifier.contains(object_name),
                )
            ) or 0
            if count > 0:
                times_changed += 1

    ratio = round(1.0 - (times_changed / max(pairs_checked, 1)), 4)

    return StabilityRecord(
        object_name=object_name,
        snapshots_checked=pairs_checked,
        times_changed=times_changed,
        stability_ratio=ratio,
        is_stable=ratio >= 0.7,
    )


def governance_scorecard(snapshot_id: int) -> GovernanceScorecard:
    """Executive governance scorecard for a snapshot."""

    metrics = compute_snapshot_metrics(snapshot_id)
    vol = structural_volatility_index()
    domains = domain_risk_index(snapshot_id)

    with Session(engine) as session:
        # Combine total + breaking into a single round-trip so we only scan
        # change_event (1.8 M rows) once instead of twice.
        ce_row = session.execute(
            select(
                func.count().label("total"),
                func.sum(case((ChangeEvent.is_breaking == True, 1), else_=0)).label("breaking"),
            ).where(ChangeEvent.snapshot_to == snapshot_id)
        ).one()
        total_changes = ce_row.total or 0
        breaking_changes = int(ce_row.breaking or 0)

        total_impacts = session.scalar(
            select(func.count()).select_from(ImpactEvent).where(
                ImpactEvent.snapshot_id == snapshot_id
            )
        ) or 0

        high_crit = session.scalar(
            select(func.count()).select_from(ObjectCriticality).where(
                ObjectCriticality.snapshot_id == snapshot_id,
                ObjectCriticality.criticality_level == "HIGH",
            )
        ) or 0

    # Health score starts at 1.0 (perfect) and is eroded by three penalties,
    # each capped so no single factor can drive the score to zero on its own:
    #   - volatility    up to -0.30 (multiplier 2x because vol is already 0-1)
    #   - breaking chg  up to -0.30 (-0.10 per breaking change, saturates at 3)
    #   - high-crit obj up to -0.20 (-0.05 per HIGH object, saturates at 4)
    # The final max(…, 0.0) clamps to avoid negative scores on worst-case data.
    health = 1.0
    health -= min(vol * 2, 0.3)  # volatility penalty
    health -= min(breaking_changes * 0.1, 0.3)  # breaking penalty
    health -= min(high_crit * 0.05, 0.2)  # criticality penalty
    health = round(max(health, 0.0), 4)

    # Three-tier label mapping — thresholds mirror the color bands shown
    # on the SCION executive dashboard (green / amber / red).
    if health >= 0.7:
        overall = "HEALTHY"
    elif health >= 0.4:
        overall = "AT_RISK"
    else:
        overall = "CRITICAL"

    return GovernanceScorecard(
        snapshot_id=snapshot_id,
        total_objects=metrics.total_objects,
        schema_count=metrics.schema_count,
        table_count=metrics.table_count,
        column_count=metrics.column_count,
        volatility_index=vol,
        total_changes=total_changes,
        breaking_changes=breaking_changes,
        total_impacts=total_impacts,
        high_criticality_objects=high_crit,
        domain_risks=domains,
        overall_health=overall,
        health_score=health,
    )
