"""Column-level diff tests for DiffEngine v5.4.

These tests validate only column-level structural behaviour. There is no
persistence of change events or impact logic.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from app.diff.diff_engine import DiffEngine
from app.diff.diff_models import Change
from app.db.base import Base
from app.db.engine import engine
from app.db.models.column_snapshot import ColumnSnapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.snapshot import Snapshot
from app.db.models.table_snapshot import TableSnapshot


def _reset_db() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _create_snapshot_with_columns(
    columns: list[tuple[str, str, str, str, bool, int]]
) -> int:
    """Create a Snapshot with schema, table, and column metadata.

    `columns` is a list of
    (schema_name, table_name, column_name, data_type, nullable, ordinal_position).

    Returns the new snapshot_id.
    """

    SessionLocal = sessionmaker(bind=engine)
    session: Session = SessionLocal()
    try:
        snapshot = Snapshot(
            snapshot_time=datetime.now(UTC),
            source_system="test_diff_columns",
            description="column-level diff",
            is_baseline=False,
        )
        session.add(snapshot)
        session.flush()

        # Ensure schemas and tables exist for all columns.
        schema_ids: dict[str, int] = {}
        table_ids: dict[tuple[str, str], int] = {}

        for schema_name, table_name, *_ in columns:
            if schema_name not in schema_ids:
                schema = SchemaSnapshot(
                    snapshot_id=snapshot.snapshot_id,
                    schema_name=schema_name,
                )
                session.add(schema)
                session.flush()
                schema_ids[schema_name] = schema.schema_id

            key = (schema_name, table_name)
            if key not in table_ids:
                table = TableSnapshot(
                    schema_id=schema_ids[schema_name],
                    table_name=table_name,
                    object_type="TABLE",
                )
                session.add(table)
                session.flush()
                table_ids[key] = table.table_id

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


def _triples_from_changes(changes: list[Change]) -> list[tuple[str, str, str]]:
    """Helper to extract (object_type, identifier, change_type) triples."""

    return [
        (c.object_type, c.object_identifier, c.change_type) for c in changes
    ]


def _column_changes_only(changes: list[Change]) -> list[Change]:
    """Filter a list of Change objects to only COLUMN-level events."""

    return [c for c in changes if c.object_type == "COLUMN"]


def test_column_added() -> None:
    """COLUMN_ADDED when a new column appears in snapshot_to."""

    _reset_db()

    snapshot_from = _create_snapshot_with_columns([
        ("public", "users", "id", "INTEGER", False, 1),
    ])
    snapshot_to = _create_snapshot_with_columns([
        ("public", "users", "id", "INTEGER", False, 1),
        ("public", "users", "email", "TEXT", True, 2),
    ])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    col_changes = _column_changes_only(changes)
    triples = _triples_from_changes(col_changes)

    assert ("COLUMN", "public.users.email", "COLUMN_ADDED") in triples

    added = next(
        c
        for c in col_changes
        if c.object_identifier == "public.users.email"
        and c.change_type == "COLUMN_ADDED"
    )
    assert added.before_state is None
    assert added.after_state == {
        "data_type": "TEXT",
        "nullable": True,
        "ordinal_position": 2,
    }


def test_column_removed() -> None:
    """COLUMN_REMOVED when a column disappears in snapshot_to."""

    _reset_db()

    snapshot_from = _create_snapshot_with_columns([
        ("public", "users", "id", "INTEGER", False, 1),
        ("public", "users", "email", "TEXT", True, 2),
    ])
    snapshot_to = _create_snapshot_with_columns([
        ("public", "users", "id", "INTEGER", False, 1),
    ])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    col_changes = _column_changes_only(changes)
    triples = _triples_from_changes(col_changes)

    assert ("COLUMN", "public.users.email", "COLUMN_REMOVED") in triples

    removed = next(
        c
        for c in col_changes
        if c.object_identifier == "public.users.email"
        and c.change_type == "COLUMN_REMOVED"
    )
    assert removed.after_state is None
    assert removed.before_state == {
        "data_type": "TEXT",
        "nullable": True,
        "ordinal_position": 2,
    }


def test_column_type_changed() -> None:
    """COLUMN_TYPE_CHANGED when data_type differs between snapshots."""

    _reset_db()

    snapshot_from = _create_snapshot_with_columns([
        ("public", "users", "age", "INTEGER", True, 2),
    ])
    snapshot_to = _create_snapshot_with_columns([
        ("public", "users", "age", "BIGINT", True, 2),
    ])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    col_changes = _column_changes_only(changes)
    triples = _triples_from_changes(col_changes)

    assert ("COLUMN", "public.users.age", "COLUMN_TYPE_CHANGED") in triples

    change = next(
        c
        for c in col_changes
        if c.object_identifier == "public.users.age"
        and c.change_type == "COLUMN_TYPE_CHANGED"
    )
    assert change.before_state == {"data_type": "INTEGER"}
    assert change.after_state == {"data_type": "BIGINT"}


def test_column_nullability_changed() -> None:
    """COLUMN_NULLABILITY_CHANGED when nullable flag changes."""

    _reset_db()

    snapshot_from = _create_snapshot_with_columns([
        ("public", "users", "email", "TEXT", False, 2),
    ])
    snapshot_to = _create_snapshot_with_columns([
        ("public", "users", "email", "TEXT", True, 2),
    ])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    col_changes = _column_changes_only(changes)
    triples = _triples_from_changes(col_changes)

    assert (
        "COLUMN",
        "public.users.email",
        "COLUMN_NULLABILITY_CHANGED",
    ) in triples

    change = next(
        c
        for c in col_changes
        if c.object_identifier == "public.users.email"
        and c.change_type == "COLUMN_NULLABILITY_CHANGED"
    )
    assert change.before_state == {"nullable": False}
    assert change.after_state == {"nullable": True}


def test_column_position_changed() -> None:
    """COLUMN_POSITION_CHANGED when ordinal_position changes."""

    _reset_db()

    snapshot_from = _create_snapshot_with_columns([
        ("public", "users", "email", "TEXT", True, 2),
    ])
    snapshot_to = _create_snapshot_with_columns([
        ("public", "users", "email", "TEXT", True, 4),
    ])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    col_changes = _column_changes_only(changes)
    triples = _triples_from_changes(col_changes)

    assert (
        "COLUMN",
        "public.users.email",
        "COLUMN_POSITION_CHANGED",
    ) in triples

    change = next(
        c
        for c in col_changes
        if c.object_identifier == "public.users.email"
        and c.change_type == "COLUMN_POSITION_CHANGED"
    )
    assert change.before_state == {"ordinal_position": 2}
    assert change.after_state == {"ordinal_position": 4}


def test_multiple_changes_on_same_column_are_not_merged() -> None:
    """Type and nullable changes on the same column must yield two events."""

    _reset_db()

    snapshot_from = _create_snapshot_with_columns([
        ("public", "users", "age", "INTEGER", False, 2),
    ])
    snapshot_to = _create_snapshot_with_columns([
        ("public", "users", "age", "BIGINT", True, 2),
    ])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    col_changes = [
        c
        for c in _column_changes_only(changes)
        if c.object_identifier == "public.users.age"
    ]
    triples = _triples_from_changes(col_changes)

    assert (
        "COLUMN",
        "public.users.age",
        "COLUMN_TYPE_CHANGED",
    ) in triples
    assert (
        "COLUMN",
        "public.users.age",
        "COLUMN_NULLABILITY_CHANGED",
    ) in triples

    # Ensure we emitted two separate Change instances.
    assert len(col_changes) == 2


def test_column_diff_is_deterministic() -> None:
    """Same inputs must always yield the same, sorted column-level result."""

    _reset_db()

    snapshot_from = _create_snapshot_with_columns([
        ("public", "users", "a", "INTEGER", False, 1),
        ("public", "users", "b", "INTEGER", True, 2),
    ])
    snapshot_to = _create_snapshot_with_columns([
        ("public", "users", "b", "BIGINT", True, 2),
        ("public", "users", "c", "TEXT", True, 3),
    ])

    engine_diff = DiffEngine()
    first = engine_diff.compute_diff(snapshot_from, snapshot_to)
    second = engine_diff.compute_diff(snapshot_from, snapshot_to)

    col_first = _column_changes_only(first)
    col_second = _column_changes_only(second)

    assert col_first == col_second

    triples = _triples_from_changes(col_first)
    assert triples == sorted(triples)
