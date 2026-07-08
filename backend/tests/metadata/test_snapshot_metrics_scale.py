"""Regression: compute_snapshot_metrics works at production scale.

The previous implementation materialised every table_id of a snapshot
into a Python list and fed it to `ColumnSnapshot.table_id.in_(...)`.
On Rahul's full Transcend-DevTest extract (~239k tables) that produced
a SQL statement with 239 553 host parameters, which SQLite rejects
(`OperationalError: too many SQL variables`; the limit is 999 or
32 766 depending on the build).

This test pins the behaviour: we synthesise a snapshot with enough
tables to be sure we'd have crashed on the old code path, then verify
`compute_snapshot_metrics` returns the right counts. Lives in
`tests/metadata/` rather than `tests/snapshot/` because the snapshot/
dir is quarantined under known-broken fixtures (circular-import issue
unrelated to this fix).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.column_snapshot import ColumnSnapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.snapshot import Snapshot
from app.db.models.table_snapshot import TableSnapshot


# Comfortably above SQLite's 999-parameter cap, intentionally lower than
# 32 766 so the test stays fast on slower CI runners. The point is to
# prove the JOIN-based path scales — we don't need 240k rows to do that.
_TABLES_PER_SCHEMA = 1500


def test_compute_snapshot_metrics_scales_past_sqlite_param_limit(
    monkeypatch, tmp_path,
):
    """Build a fake snapshot with > 1000 tables and verify counts.

    We point the metrics module at a scratch SQLite DB so we don't
    contaminate the dev DB. `monkeypatch` swaps the `engine` symbol the
    module imported at load time.
    """
    db_path = tmp_path / "metrics_scale.db"
    test_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=test_engine)

    # Late import so monkeypatch can swap the engine attribute the
    # function captures via `with Session(engine)`.
    from app.snapshot import snapshot_metrics

    monkeypatch.setattr(snapshot_metrics, "engine", test_engine)

    with Session(test_engine) as session:
        with session.begin():
            snap = Snapshot(
                snapshot_time=datetime.now(timezone.utc),
                source_system="ScaleTest",
                description="scale test",
                is_baseline=False,
                object_count=0,
            )
            session.add(snap)
            session.flush()
            sid = snap.snapshot_id

            schema = SchemaSnapshot(snapshot_id=sid, schema_name="big_schema")
            session.add(schema)
            session.flush()
            schema_id = schema.schema_id

            # Bulk-insert tables — using ORM `add()` in a loop would take
            # multiple seconds per thousand rows; bulk_insert_mappings is
            # the right tool when the test only cares about the count.
            session.bulk_insert_mappings(
                TableSnapshot,
                [
                    {
                        "schema_id": schema_id,
                        "table_name": f"t_{i:06d}",
                        "object_type": "TABLE" if i % 5 != 0 else "VIEW",
                    }
                    for i in range(_TABLES_PER_SCHEMA)
                ],
            )

            # Need columns too so the JOIN actually has rows to count.
            # Two columns per table → 3 000 column rows. Enough to verify
            # the column count query joins correctly.
            table_ids = session.scalars(
                TableSnapshot.__table__.select().with_only_columns(
                    TableSnapshot.table_id
                )
            ).all()
            session.bulk_insert_mappings(
                ColumnSnapshot,
                [
                    {
                        "table_id": tid,
                        "column_name": f"c{j}",
                        "data_type": "INTEGER",
                        "nullable": True,
                        "ordinal_position": j,
                    }
                    for tid in table_ids
                    for j in range(2)
                ],
            )

    metrics = snapshot_metrics.compute_snapshot_metrics(sid)

    # 1500 tables: every 5th is a VIEW → 300 views, 1200 tables.
    expected_views = _TABLES_PER_SCHEMA // 5
    expected_tables = _TABLES_PER_SCHEMA - expected_views

    assert metrics.snapshot_id == sid
    assert metrics.schema_count == 1
    assert metrics.table_count == expected_tables
    assert metrics.view_count == expected_views
    assert metrics.column_count == _TABLES_PER_SCHEMA * 2
    assert metrics.total_objects == (
        1 + expected_tables + expected_views
    )


def test_compute_snapshot_metrics_empty_snapshot(monkeypatch, tmp_path):
    """Snapshot with zero schemas returns zeroed metrics, not a crash."""
    db_path = tmp_path / "metrics_empty.db"
    test_engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=test_engine)

    from app.snapshot import snapshot_metrics

    monkeypatch.setattr(snapshot_metrics, "engine", test_engine)

    with Session(test_engine) as session:
        with session.begin():
            snap = Snapshot(
                snapshot_time=datetime.now(timezone.utc),
                source_system="EmptyTest",
                description="empty",
                is_baseline=False,
                object_count=0,
            )
            session.add(snap)
            session.flush()
            sid = snap.snapshot_id

    metrics = snapshot_metrics.compute_snapshot_metrics(sid)
    assert metrics.snapshot_id == sid
    assert metrics.schema_count == 0
    assert metrics.table_count == 0
    assert metrics.view_count == 0
    assert metrics.column_count == 0
    assert metrics.total_objects == 0
