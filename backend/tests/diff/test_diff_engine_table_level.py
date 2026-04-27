"""Table-level diff tests for DiffEngine v5.3.

These tests validate only table-level behaviour. Column diffs, persistence of
change events, and rule engines are explicitly out of scope.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from app.diff.diff_engine import DiffEngine
from app.diff.diff_models import Change
from app.db.base import Base
from app.db.engine import engine
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.snapshot import Snapshot
from app.db.models.table_snapshot import TableSnapshot


def _reset_db() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _create_snapshot_with_tables(
    tables: list[tuple[str, str, str]]
) -> int:
    """Create a Snapshot with associated SchemaSnapshot and TableSnapshot rows.

    `tables` is a list of (schema_name, table_name, object_type) tuples.

    Returns the new snapshot_id.
    """

    SessionLocal = sessionmaker(bind=engine)
    session: Session = SessionLocal()
    try:
        snapshot = Snapshot(
            snapshot_time=datetime.now(UTC),
            source_system="test_diff_tables",
            description="table-level diff",
            is_baseline=False,
        )
        session.add(snapshot)
        session.flush()

        # Ensure schemas exist for all tables.
        schema_ids: dict[str, int] = {}
        for schema_name, _, _ in tables:
            if schema_name not in schema_ids:
                schema = SchemaSnapshot(
                    snapshot_id=snapshot.snapshot_id,
                    schema_name=schema_name,
                )
                session.add(schema)
                session.flush()
                schema_ids[schema_name] = schema.schema_id

        # Create tables.
        for schema_name, table_name, object_type in tables:
            session.add(
                TableSnapshot(
                    schema_id=schema_ids[schema_name],
                    table_name=table_name,
                    object_type=object_type,
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


def _table_changes_only(changes: list[Change]) -> list[Change]:
    """Filter a list of Change objects to only TABLE-level events."""

    return [c for c in changes if c.object_type == "TABLE"]


def test_table_added() -> None:
    """TABLE_ADDED when a new table appears in snapshot_to.

    Schemas remain the same; only a new table is introduced.
    """

    _reset_db()

    snapshot_from = _create_snapshot_with_tables([
        ("public", "users", "TABLE"),
    ])
    snapshot_to = _create_snapshot_with_tables([
        ("public", "users", "TABLE"),
        ("public", "orders", "TABLE"),
    ])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    table_changes = _table_changes_only(changes)
    assert len(table_changes) == 1

    change = table_changes[0]
    assert change.object_type == "TABLE"
    assert change.object_identifier == "public.orders"
    assert change.change_type == "TABLE_ADDED"
    assert change.before_state is None
    assert change.after_state == {
        "schema_name": "public",
        "table_name": "orders",
        "object_type": "TABLE",
    }


def test_table_removed() -> None:
    """TABLE_REMOVED when a table disappears in snapshot_to."""

    _reset_db()

    snapshot_from = _create_snapshot_with_tables([
        ("public", "users", "TABLE"),
        ("public", "orders", "TABLE"),
    ])
    snapshot_to = _create_snapshot_with_tables([
        ("public", "users", "TABLE"),
    ])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    table_changes = _table_changes_only(changes)
    assert len(table_changes) == 1

    change = table_changes[0]
    assert change.object_type == "TABLE"
    assert change.object_identifier == "public.orders"
    assert change.change_type == "TABLE_REMOVED"
    assert change.before_state == {
        "schema_name": "public",
        "table_name": "orders",
        "object_type": "TABLE",
    }
    assert change.after_state is None


def test_table_type_changed() -> None:
    """TABLE_TYPE_CHANGED when the object_type flips between snapshots."""

    _reset_db()

    snapshot_from = _create_snapshot_with_tables([
        ("public", "customers", "TABLE"),
    ])
    snapshot_to = _create_snapshot_with_tables([
        ("public", "customers", "VIEW"),
    ])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    table_changes = _table_changes_only(changes)
    assert len(table_changes) == 1

    change = table_changes[0]
    assert change.object_type == "TABLE"
    assert change.object_identifier == "public.customers"
    assert change.change_type == "TABLE_TYPE_CHANGED"
    assert change.before_state == {"object_type": "TABLE"}
    assert change.after_state == {"object_type": "VIEW"}


def test_multiple_schemas_isolated_comparison() -> None:
    """Same table name in different schemas must be treated independently."""

    _reset_db()

    # users table present in both schemas in snapshot_from
    snapshot_from = _create_snapshot_with_tables([
        ("public", "users", "TABLE"),
        ("analytics", "users", "TABLE"),
    ])

    # public.users removed; analytics.users changed type
    snapshot_to = _create_snapshot_with_tables([
        ("analytics", "users", "VIEW"),
    ])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    table_changes = _table_changes_only(changes)
    triples = _triples_from_changes(table_changes)

    assert ("TABLE", "public.users", "TABLE_REMOVED") in triples
    assert ("TABLE", "analytics.users", "TABLE_TYPE_CHANGED") in triples


def test_table_diff_is_deterministic() -> None:
    """Same inputs must always yield the same, sorted table-level result."""

    _reset_db()

    snapshot_from = _create_snapshot_with_tables([
        ("public", "a", "TABLE"),
        ("public", "b", "VIEW"),
    ])
    snapshot_to = _create_snapshot_with_tables([
        ("public", "b", "TABLE"),
        ("public", "c", "TABLE"),
    ])

    engine_diff = DiffEngine()
    first = engine_diff.compute_diff(snapshot_from, snapshot_to)
    second = engine_diff.compute_diff(snapshot_from, snapshot_to)

    table_first = _table_changes_only(first)
    table_second = _table_changes_only(second)

    assert table_first == table_second

    triples = _triples_from_changes(table_first)
    assert triples == sorted(triples)
