"""Snapshot-level metrics: object counts, growth rate, volatility index."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot
from app.diff.diff_models import ChangeEvent


@dataclass
class SnapshotMetrics:
    snapshot_id: int
    schema_count: int = 0
    table_count: int = 0
    view_count: int = 0
    column_count: int = 0
    total_objects: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GrowthMetrics:
    snapshot_from: int
    snapshot_to: int
    objects_added: int = 0
    objects_removed: int = 0
    net_change: int = 0
    growth_percentage: float = 0.0
    schemas_added: int = 0
    schemas_removed: int = 0
    tables_added: int = 0
    tables_removed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_snapshot_metrics(snapshot_id: int) -> SnapshotMetrics:
    """Count schemas, tables, views, and columns for a snapshot."""

    with Session(engine) as session:
        schema_ids = session.scalars(
            select(SchemaSnapshot.schema_id)
            .where(SchemaSnapshot.snapshot_id == snapshot_id)
        ).all()

        schema_count = len(schema_ids)

        if not schema_ids:
            return SnapshotMetrics(snapshot_id=snapshot_id)

        table_rows = session.execute(
            select(TableSnapshot.object_type, func.count())
            .where(TableSnapshot.schema_id.in_(schema_ids))
            .group_by(TableSnapshot.object_type)
        ).all()

        # object_type has only two legal values today (TABLE/VIEW) but we
        # defensively bucket anything non-VIEW as a table — future engines
        # may emit variants (MATERIALIZED_VIEW, EXTERNAL_TABLE, etc.) that
        # should still count towards the "table-like" total.
        table_count = 0
        view_count = 0
        for obj_type, cnt in table_rows:
            if obj_type == "VIEW":
                view_count = cnt
            else:
                table_count += cnt

        table_ids = session.scalars(
            select(TableSnapshot.table_id)
            .where(TableSnapshot.schema_id.in_(schema_ids))
        ).all()

        column_count = 0
        if table_ids:
            column_count = session.scalar(
                select(func.count())
                .where(ColumnSnapshot.table_id.in_(table_ids))
            ) or 0

    total = schema_count + table_count + view_count + column_count

    return SnapshotMetrics(
        snapshot_id=snapshot_id,
        schema_count=schema_count,
        table_count=table_count,
        view_count=view_count,
        column_count=column_count,
        total_objects=total,
    )


def compute_growth_rate(snapshot_from: int, snapshot_to: int) -> GrowthMetrics:
    """Compute growth between two snapshots based on change events."""

    metrics_from = compute_snapshot_metrics(snapshot_from)
    metrics_to = compute_snapshot_metrics(snapshot_to)

    # Count changes from diff
    with Session(engine) as session:
        events = session.query(ChangeEvent).filter(
            ChangeEvent.snapshot_from == snapshot_from,
            ChangeEvent.snapshot_to == snapshot_to,
        ).all()

    added = sum(1 for e in events if "ADDED" in (e.change_type or ""))
    removed = sum(1 for e in events if "REMOVED" in (e.change_type or ""))
    schemas_added = sum(1 for e in events if e.change_type == "SCHEMA_ADDED")
    schemas_removed = sum(1 for e in events if e.change_type == "SCHEMA_REMOVED")
    tables_added = sum(1 for e in events if e.change_type == "TABLE_ADDED")
    tables_removed = sum(1 for e in events if e.change_type == "TABLE_REMOVED")

    # Guard against divide-by-zero on an empty "from" snapshot: max(…, 1)
    # yields a 100% figure per net-added object, which is a sensible
    # starting-from-nothing growth picture rather than a crash.
    net = added - removed
    base = max(metrics_from.total_objects, 1)
    pct = round((net / base) * 100, 2)

    return GrowthMetrics(
        snapshot_from=snapshot_from,
        snapshot_to=snapshot_to,
        objects_added=added,
        objects_removed=removed,
        net_change=net,
        growth_percentage=pct,
        schemas_added=schemas_added,
        schemas_removed=schemas_removed,
        tables_added=tables_added,
        tables_removed=tables_removed,
    )


def compute_volatility_index(snapshot_ids: List[int] | None = None) -> float:
    """Compute a 0.0-1.0 volatility index across snapshots.

    volatility = average(changes_per_pair / total_objects) across consecutive pairs.
    0.0 = completely stable, 1.0 = everything changes every time.
    """

    with Session(engine) as session:
        if snapshot_ids is None:
            snapshot_ids = list(session.scalars(
                select(Snapshot.snapshot_id).order_by(Snapshot.snapshot_time)
            ).all())

    # Need at least 2 snapshots to form a single pair; otherwise volatility
    # is undefined and we return 0.0 (interpreted as "perfectly stable").
    if len(snapshot_ids) < 2:
        return 0.0

    # Average ratio of (changes in pair / total objects in the newer snap)
    # across every consecutive pair. Using the newer snap as denominator
    # matches the "how much of today's world changed" intuition.
    ratios = []
    for i in range(len(snapshot_ids) - 1):
        sid_from = snapshot_ids[i]
        sid_to = snapshot_ids[i + 1]

        metrics = compute_snapshot_metrics(sid_to)
        total = max(metrics.total_objects, 1)

        with Session(engine) as session:
            change_count = session.scalar(
                select(func.count()).select_from(ChangeEvent).where(
                    ChangeEvent.snapshot_from == sid_from,
                    ChangeEvent.snapshot_to == sid_to,
                )
            ) or 0

        ratios.append(change_count / total)

    return round(sum(ratios) / len(ratios), 4) if ratios else 0.0
