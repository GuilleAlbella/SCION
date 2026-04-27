"""Schema-level diff tests for DiffEngine v5.2.

These tests validate only schema-level behaviour. Table and column diffs are
explicitly out of scope for v5.2.
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


def _reset_db() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _create_snapshot_with_schemas(names: list[str]) -> int:
    """Create a Snapshot row and associated SchemaSnapshot rows.

    Returns the new snapshot_id.
    """

    SessionLocal = sessionmaker(bind=engine)
    session: Session = SessionLocal()
    try:
        snapshot = Snapshot(
            snapshot_time=datetime.now(UTC),
            source_system="test_diff",
            description="schema-level diff",
            is_baseline=False,
        )
        session.add(snapshot)
        session.flush()

        for name in names:
            session.add(
                SchemaSnapshot(
                    snapshot_id=snapshot.snapshot_id,
                    schema_name=name,
                )
            )

        session.commit()
        return snapshot.snapshot_id
    finally:
        session.close()


def _names_from_changes(changes: list[Change]) -> list[tuple[str, str, str]]:
    """Helper to extract (object_type, identifier, change_type) triples."""

    return [
        (c.object_type, c.object_identifier, c.change_type) for c in changes
    ]


def test_no_changes_when_schemas_are_identical() -> None:
    """Diff must be empty when both snapshots have the same schemas."""

    _reset_db()

    snapshot_from = _create_snapshot_with_schemas(["public", "analytics"])
    snapshot_to = _create_snapshot_with_schemas(["public", "analytics"])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    assert changes == []


def test_schema_added() -> None:
    """Schema present only in snapshot_to must be reported as SCHEMA_ADDED."""

    _reset_db()

    snapshot_from = _create_snapshot_with_schemas([])
    snapshot_to = _create_snapshot_with_schemas(["public"])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    assert len(changes) == 1
    change = changes[0]

    assert change.object_type == "SCHEMA"
    assert change.object_identifier == "public"
    assert change.change_type == "SCHEMA_ADDED"
    assert change.before_state is None
    assert change.after_state == {"schema_name": "public"}


def test_schema_removed() -> None:
    """Schema present only in snapshot_from must be reported as SCHEMA_REMOVED."""

    _reset_db()

    snapshot_from = _create_snapshot_with_schemas(["legacy"])
    snapshot_to = _create_snapshot_with_schemas([])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    assert len(changes) == 1
    change = changes[0]

    assert change.object_type == "SCHEMA"
    assert change.object_identifier == "legacy"
    assert change.change_type == "SCHEMA_REMOVED"
    assert change.before_state == {"schema_name": "legacy"}
    assert change.after_state is None


def test_mixed_schema_changes() -> None:
    """Diff must detect both removed and added schemas in a single run."""

    _reset_db()

    snapshot_from = _create_snapshot_with_schemas(["a", "b"])
    snapshot_to = _create_snapshot_with_schemas(["b", "c"])

    engine_diff = DiffEngine()
    changes = engine_diff.compute_diff(snapshot_from, snapshot_to)

    triples = _names_from_changes(changes)

    # Expect one removal (a) and one addition (c).
    assert (
        ("SCHEMA", "a", "SCHEMA_REMOVED") in triples
    ), f"Expected SCHEMA_REMOVED for 'a', got {triples!r}"
    assert (
        ("SCHEMA", "c", "SCHEMA_ADDED") in triples
    ), f"Expected SCHEMA_ADDED for 'c', got {triples!r}"


def test_schema_diff_is_deterministic() -> None:
    """Same inputs must always yield the same, sorted result."""

    _reset_db()

    snapshot_from = _create_snapshot_with_schemas(["z", "m"])
    snapshot_to = _create_snapshot_with_schemas(["m", "x"])

    engine_diff = DiffEngine()
    first = engine_diff.compute_diff(snapshot_from, snapshot_to)
    second = engine_diff.compute_diff(snapshot_from, snapshot_to)

    assert first == second

    # Verify that the result list is sorted according to
    # (object_type, object_identifier, change_type).
    triples = _names_from_changes(first)
    assert triples == sorted(triples)
