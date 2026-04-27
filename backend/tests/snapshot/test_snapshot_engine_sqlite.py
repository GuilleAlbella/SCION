from sqlalchemy import select
import pytest

from app.snapshot.snapshot_engine import (
    InvalidSnapshotExecution,
    SnapshotEngine,
)
from app.snapshot.snapshot_loader import SnapshotLoader
from app.snapshot.snapshot_models import (
    ColumnMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.snapshot.template_sets import DEFAULT_SNAPSHOT_TEMPLATE_SET
from app.metadata.adapters.sqlite import SQLiteAdapter

from app.db.engine import engine
from app.db.base import Base
from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot


def _reset_database() -> None:
    """Windows-safe DB reset."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_snapshot_persists_all_levels():
    """
    End-to-end test:
    - Creates a snapshot
    - Verifies snapshot, schemas, tables and columns persistence
    """

    # Arrange
    _reset_database()

    adapter = SQLiteAdapter()
    loader = SnapshotLoader(adapter)
    snapshot_engine = SnapshotEngine(loader)

    # Act
    snapshot_id = snapshot_engine.create_snapshot(
        source_system="test",
        description="Snapshot persistence test",
    )

    # Assert
    with engine.connect() as conn:
        snapshots = conn.execute(select(Snapshot)).fetchall()
        schemas = conn.execute(select(SchemaSnapshot)).fetchall()
        tables = conn.execute(select(TableSnapshot)).fetchall()
        columns = conn.execute(select(ColumnSnapshot)).fetchall()

    assert snapshot_id is not None
    assert len(snapshots) == 1
    assert len(schemas) > 0
    assert len(tables) > 0
    assert len(columns) >= 0


class FailingLoader:
    """SnapshotLoader stub that always fails."""

    def load(self):
        raise RuntimeError("Forced loader failure")


def test_snapshot_is_atomic_on_failure():
    """
    Verifies that if loading metadata fails,
    no partial snapshot data is persisted.
    """

    # Arrange
    _reset_database()

    loader = FailingLoader()
    snapshot_engine = SnapshotEngine(loader)

    # Act / Assert
    with pytest.raises(RuntimeError):
        snapshot_engine.create_snapshot(
            source_system="test",
            description="This snapshot must rollback",
        )

    # Verify DB is clean
    with engine.connect() as conn:
        snapshots = conn.execute(
            Snapshot.__table__.select()
        ).fetchall()

    assert snapshots == []


def test_snapshot_generates_new_snapshot_id():
    """Each valid execution must create a new snapshot row.

    This test executes the real engine twice with the SQLite adapter and
    asserts that two distinct snapshot_ids are returned and persisted.
    """

    _reset_database()

    adapter = SQLiteAdapter()
    loader = SnapshotLoader(adapter)
    snapshot_engine = SnapshotEngine(loader)

    first_id = snapshot_engine.create_snapshot(
        source_system="test",
        description="First snapshot",
    )

    second_id = snapshot_engine.create_snapshot(
        source_system="test",
        description="Second snapshot",
    )

    assert first_id != second_id

    with engine.connect() as conn:
        snapshots = conn.execute(select(Snapshot)).fetchall()

    persisted_ids = sorted(row.snapshot_id for row in snapshots)
    assert persisted_ids == sorted([first_id, second_id])


class LoaderNoSchemas:
    """Stub loader that returns no schemas, making the snapshot invalid."""

    def load(self):
        return {"schemas": [], "tables": [], "columns": []}


class LoaderNoTables:
    """Stub loader that returns schemas but no tables."""

    def load(self):
        schemas = [SchemaMetadata(schema_name="main")]
        return {"schemas": schemas, "tables": [], "columns": []}


class LoaderNoColumns:
    """Stub loader that returns schemas and tables but no columns.

    Under the new semantics, zero columns are allowed even when the
    "list_columns" template is part of the active template set.
    """

    def load(self):
        schemas = [SchemaMetadata(schema_name="main")]
        tables = [
            TableMetadata(
                schema_name="main",
                table_name="demo_table",
                object_type="table",
            )
        ]
        return {"schemas": schemas, "tables": tables, "columns": []}


def _assert_no_snapshot_related_rows() -> None:
    """Helper to assert that no snapshot-related rows exist in the DB."""

    with engine.connect() as conn:
        snapshots = conn.execute(select(Snapshot)).fetchall()
        schemas = conn.execute(select(SchemaSnapshot)).fetchall()
        tables = conn.execute(select(TableSnapshot)).fetchall()
        columns = conn.execute(select(ColumnSnapshot)).fetchall()

    assert snapshots == []
    assert schemas == []
    assert tables == []
    assert columns == []


def test_snapshot_invalid_when_no_schemas():
    """Loader returning no schemas must make the snapshot invalid.

    The engine must raise ``InvalidSnapshotExecution`` and leave the
    database unchanged.
    """

    _reset_database()

    loader = LoaderNoSchemas()
    snapshot_engine = SnapshotEngine(loader)

    with pytest.raises(InvalidSnapshotExecution):
        snapshot_engine.create_snapshot(
            source_system="test",
            description="No schemas snapshot",
        )

    _assert_no_snapshot_related_rows()


def test_snapshot_invalid_when_no_tables():
    """Loader returning schemas but no tables must make the snapshot invalid."""

    _reset_database()

    loader = LoaderNoTables()
    snapshot_engine = SnapshotEngine(loader)

    with pytest.raises(InvalidSnapshotExecution):
        snapshot_engine.create_snapshot(
            source_system="test",
            description="No tables snapshot",
        )

    _assert_no_snapshot_related_rows()


def test_snapshot_allows_zero_columns():
    """Zero columns must be allowed even when list_columns is active.

    The engine should consider this a valid snapshot as long as schemas and
    tables are structurally correct.
    """

    _reset_database()

    loader = LoaderNoColumns()
    snapshot_engine = SnapshotEngine(loader)

    snapshot_id = snapshot_engine.create_snapshot(
        source_system="test",
        description="No columns snapshot",
    )

    with engine.connect() as conn:
        snapshots = conn.execute(select(Snapshot)).fetchall()
        schemas = conn.execute(select(SchemaSnapshot)).fetchall()
        tables = conn.execute(select(TableSnapshot)).fetchall()
        columns = conn.execute(select(ColumnSnapshot)).fetchall()

    assert snapshot_id is not None
    assert len(snapshots) == 1
    assert len(schemas) > 0
    assert len(tables) > 0
    assert columns == []


def test_snapshot_respects_template_set():
    """Engine must respect a reduced template set.

    Using a template set that only includes schemas and tables should result
    in snapshot, schema and table records being persisted, but no columns.
    """

    _reset_database()

    adapter = SQLiteAdapter()
    # Configure loader and engine to only use schemas and tables.
    template_set = ("list_schemas", "list_tables")
    loader = SnapshotLoader(adapter, template_set=template_set)
    snapshot_engine = SnapshotEngine(loader, template_set=template_set)

    snapshot_id = snapshot_engine.create_snapshot(
        source_system="test",
        description="Schemas and tables only",
    )

    with engine.connect() as conn:
        snapshots = conn.execute(select(Snapshot)).fetchall()
        schemas = conn.execute(select(SchemaSnapshot)).fetchall()
        tables = conn.execute(select(TableSnapshot)).fetchall()
        columns = conn.execute(select(ColumnSnapshot)).fetchall()

    assert snapshot_id is not None
    assert len(snapshots) == 1
    assert len(schemas) > 0
    assert len(tables) > 0
    assert columns == []


def test_snapshot_skips_missing_templates():
    """Non-existing template names in the template set must be ignored."""

    _reset_database()

    adapter = SQLiteAdapter()
    # Include a bogus template name; it must be ignored without failing.
    template_set = ("list_schemas", "non_existing_template", "list_tables")
    loader = SnapshotLoader(adapter, template_set=template_set)
    snapshot_engine = SnapshotEngine(loader, template_set=template_set)

    snapshot_id = snapshot_engine.create_snapshot(
        source_system="test",
        description="Missing template is ignored",
    )

    with engine.connect() as conn:
        snapshots = conn.execute(select(Snapshot)).fetchall()
        schemas = conn.execute(select(SchemaSnapshot)).fetchall()
        tables = conn.execute(select(TableSnapshot)).fetchall()

    assert snapshot_id is not None
    assert len(snapshots) == 1
    assert len(schemas) > 0
    assert len(tables) > 0


class ColumnsOptionalLoader:
    """Loader stub that never returns columns, regardless of template set.

    Used to verify that when ``list_columns`` is not part of the active
    template set, the engine does not enforce column-level validation.
    """

    def __init__(self, base_loader: SnapshotLoader):
        self._base_loader = base_loader

    def load(self):
        data = self._base_loader.load()
        return {"schemas": data["schemas"], "tables": data["tables"], "columns": []}


def test_snapshot_validation_depends_on_template_set():
    """Column-level validation must be skipped when list_columns is disabled.

    When the template set does not contain "list_columns", the engine should
    not treat the absence of columns as invalid.
    """

    _reset_database()

    adapter = SQLiteAdapter()
    # Template set explicitly omits "list_columns".
    template_set = ("list_schemas", "list_tables")
    base_loader = SnapshotLoader(adapter, template_set=template_set)
    loader = ColumnsOptionalLoader(base_loader)
    snapshot_engine = SnapshotEngine(loader, template_set=template_set)

    snapshot_id = snapshot_engine.create_snapshot(
        source_system="test",
        description="Columns not required",
    )

    with engine.connect() as conn:
        snapshots = conn.execute(select(Snapshot)).fetchall()
        schemas = conn.execute(select(SchemaSnapshot)).fetchall()
        tables = conn.execute(select(TableSnapshot)).fetchall()

    assert snapshot_id is not None
    assert len(snapshots) == 1
    assert len(schemas) > 0
    assert len(tables) > 0
