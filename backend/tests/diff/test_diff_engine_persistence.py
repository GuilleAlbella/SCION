"""Persistence tests for DiffEngine v5.5.

These tests validate that change events are persisted in an append-only,
immutable, and idempotent way without altering diff logic.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from app.diff.diff_engine import DiffEngine
from app.diff.diff_models import ChangeEvent
from app.db.base import Base
from app.db.engine import engine
from app.db.models.column_snapshot import ColumnSnapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.snapshot import Snapshot
from app.db.models.table_snapshot import TableSnapshot


def _reset_db() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _create_snapshot_with_full_structure(
    *,
    schemas: list[str],
    tables: list[tuple[str, str, str]],
    columns: list[tuple[str, str, str, str, bool, int]],
) -> int:
    """Create a snapshot with schemas, tables, and columns.

    - `schemas`: list of schema names.
    - `tables`: (schema_name, table_name, object_type).
    - `columns`: (schema_name, table_name, column_name, data_type, nullable, ordinal_position).
    """

    SessionLocal = sessionmaker(bind=engine)
    session: Session = SessionLocal()
    try:
        snapshot = Snapshot(
            snapshot_time=datetime.now(UTC),
            source_system="test_diff_persistence",
            description="persistence test snapshot",
            is_baseline=False,
        )
        session.add(snapshot)
        session.flush()

        schema_ids: dict[str, int] = {}
        for schema_name in schemas:
            schema = SchemaSnapshot(
                snapshot_id=snapshot.snapshot_id,
                schema_name=schema_name,
            )
            session.add(schema)
            session.flush()
            schema_ids[schema_name] = schema.schema_id

        table_ids: dict[tuple[str, str], int] = {}
        for schema_name, table_name, object_type in tables:
            table = TableSnapshot(
                schema_id=schema_ids[schema_name],
                table_name=table_name,
                object_type=object_type,
            )
            session.add(table)
            session.flush()
            table_ids[(schema_name, table_name)] = table.table_id

        for (
            schema_name,
            table_name,
            column_name,
            data_type,
            nullable,
            ordinal_position,
        ) in columns:
            table_id = table_ids[(schema_name, table_name)]
            session.add(
                ColumnSnapshot(
                    table_id=table_id,
                    column_name=column_name,
                    data_type=data_type,
                    nullable=nullable,
                    ordinal_position=ordinal_position,
                )
            )

        session.commit()
        return snapshot.snapshot_id
    finally:
        session.close()


def _count_events(snapshot_from: int, snapshot_to: int) -> int:
    SessionLocal = sessionmaker(bind=engine)
    session: Session = SessionLocal()
    try:
        return (
            session.query(ChangeEvent)
            .filter(
                ChangeEvent.snapshot_from == snapshot_from,
                ChangeEvent.snapshot_to == snapshot_to,
            )
            .count()
        )
    finally:
        session.close()


def _load_events(snapshot_from: int, snapshot_to: int) -> list[ChangeEvent]:
    SessionLocal = sessionmaker(bind=engine)
    session: Session = SessionLocal()
    try:
        return (
            session.query(ChangeEvent)
            .filter(
                ChangeEvent.snapshot_from == snapshot_from,
                ChangeEvent.snapshot_to == snapshot_to,
            )
            .order_by(
                ChangeEvent.object_type,
                ChangeEvent.object_identifier,
                ChangeEvent.change_type,
                ChangeEvent.change_id,
            )
            .all()
        )
    finally:
        session.close()


def test_events_are_persisted() -> None:
    """Diff between two snapshots must persist events in change_event."""

    _reset_db()

    snapshot_from = _create_snapshot_with_full_structure(
        schemas=["public"],
        tables=[("public", "users", "TABLE")],
        columns=[("public", "users", "id", "INTEGER", False, 1)],
    )
    snapshot_to = _create_snapshot_with_full_structure(
        schemas=["public"],
        tables=[("public", "users", "TABLE")],
        columns=[
            ("public", "users", "id", "INTEGER", False, 1),
            ("public", "users", "email", "TEXT", True, 2),
        ],
    )

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    count = _count_events(snapshot_from, snapshot_to)
    assert count == len(changes)
    assert count > 0


def test_idempotency_same_pair_does_not_duplicate_events() -> None:
    """Running diff twice for the same pair must not create duplicate events."""

    _reset_db()

    snapshot_from = _create_snapshot_with_full_structure(
        schemas=["public"],
        tables=[("public", "users", "TABLE")],
        columns=[("public", "users", "id", "INTEGER", False, 1)],
    )
    snapshot_to = _create_snapshot_with_full_structure(
        schemas=["public"],
        tables=[("public", "users", "TABLE")],
        columns=[
            ("public", "users", "id", "INTEGER", False, 1),
            ("public", "users", "email", "TEXT", True, 2),
        ],
    )

    engine_diff = DiffEngine()
    engine_diff.compute_diff(snapshot_from, snapshot_to)
    first_count = _count_events(snapshot_from, snapshot_to)

    # Second run should reuse existing events and not insert new ones.
    engine_diff.compute_diff(snapshot_from, snapshot_to)
    second_count = _count_events(snapshot_from, snapshot_to)

    assert first_count == second_count


def test_events_are_immutable_on_rerun() -> None:
    """Re-running diff must not change detected_at or states of existing events."""

    _reset_db()

    snapshot_from = _create_snapshot_with_full_structure(
        schemas=["public"],
        tables=[("public", "users", "TABLE")],
        columns=[("public", "users", "age", "INTEGER", False, 1)],
    )
    snapshot_to = _create_snapshot_with_full_structure(
        schemas=["public"],
        tables=[("public", "users", "TABLE")],
        columns=[("public", "users", "age", "BIGINT", True, 1)],
    )

    engine_diff = DiffEngine()
    engine_diff.compute_diff(snapshot_from, snapshot_to)
    before_events = _load_events(snapshot_from, snapshot_to)

    # Capture a simple snapshot of event fields.
    snapshot_before = [
        (
            e.object_type,
            e.object_identifier,
            e.change_type,
            e.before_state,
            e.after_state,
            e.detected_at,
        )
        for e in before_events
    ]

    engine_diff.compute_diff(snapshot_from, snapshot_to)
    after_events = _load_events(snapshot_from, snapshot_to)

    snapshot_after = [
        (
            e.object_type,
            e.object_identifier,
            e.change_type,
            e.before_state,
            e.after_state,
            e.detected_at,
        )
        for e in after_events
    ]

    assert snapshot_before == snapshot_after


def test_mixed_change_types_persisted() -> None:
    """Schema, table, and column changes must all be persisted."""

    _reset_db()

    # snapshot_from: one schema, one table, one column
    snapshot_from = _create_snapshot_with_full_structure(
        schemas=["public"],
        tables=[("public", "users", "TABLE")],
        columns=[("public", "users", "id", "INTEGER", False, 1)],
    )

    # snapshot_to: different schema set, table type change, and column changes
    snapshot_to = _create_snapshot_with_full_structure(
        schemas=["public", "analytics"],
        tables=[
            ("public", "users", "VIEW"),  # TABLE_TYPE_CHANGED
            ("analytics", "events", "TABLE"),  # TABLE_ADDED under new schema
        ],
        columns=[
            ("public", "users", "id", "BIGINT", False, 1),  # COLUMN_TYPE_CHANGED
            ("analytics", "events", "event_id", "INTEGER", False, 1),
        ],
    )

    engine_diff = DiffEngine()
    engine_diff.compute_diff(snapshot_from, snapshot_to)

    events = _load_events(snapshot_from, snapshot_to)
    types = {(e.object_type, e.change_type) for e in events}

    # At least one schema-level, one table-level, and one column-level change.
    assert any(t[0] == "SCHEMA" for t in types)
    assert any(t[0] == "TABLE" for t in types)
    assert any(t[0] == "COLUMN" for t in types)


def test_persistence_is_transactional_on_failure(monkeypatch) -> None:
    """If persistence fails midway, no partial change_event rows are committed."""

    _reset_db()

    snapshot_from = _create_snapshot_with_full_structure(
        schemas=["public"],
        tables=[("public", "users", "TABLE")],
        columns=[
            ("public", "users", "id", "INTEGER", False, 1),
            ("public", "users", "email", "TEXT", True, 2),
        ],
    )
    snapshot_to = _create_snapshot_with_full_structure(
        schemas=["public"],
        tables=[("public", "users", "TABLE")],
        columns=[
            ("public", "users", "id", "INTEGER", False, 1),
            ("public", "users", "email", "TEXT", True, 3),
        ],
    )

    engine_diff = DiffEngine()

    # Monkeypatch ChangeEvent.__init__ to raise on the second insert.
    original_init = ChangeEvent.__init__

    call_count = {"n": 0}

    def failing_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("Simulated persistence failure")
        original_init(self, *args, **kwargs)

    monkeypatch.setattr("app.diff.diff_models.ChangeEvent.__init__", failing_init)

    try:
        try:
            engine_diff.compute_diff(snapshot_from, snapshot_to)
        except RuntimeError:
            pass

        # After the failure, there must be no rows for this snapshot pair.
        assert _count_events(snapshot_from, snapshot_to) == 0
    finally:
        monkeypatch.setattr("app.diff.diff_models.ChangeEvent.__init__", original_init)
