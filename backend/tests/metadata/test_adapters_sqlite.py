"""Smoke tests for the SQLite metadata adapter.

These tests validate that the SQLite adapter renders non-empty, read-only SQL
strings for each template type.
"""

from __future__ import annotations

from app.metadata.adapters.sqlite import SQLiteAdapter
from app.metadata.templates.column import ColumnTemplate
from app.metadata.templates.schema import SchemaTemplate
from app.metadata.templates.snapshot import SnapshotTemplate
from app.metadata.templates.table import TableTemplate


def _assert_read_only_sql(sql: str) -> None:
    """Assert that the generated SQL is non-empty and read-only.

    For SQLite, both SELECT and PRAGMA statements are used for metadata
    inspection, so either prefix is acceptable.
    """

    assert isinstance(sql, str)
    stripped = sql.lstrip()
    assert stripped, "SQL must not be empty"
    upper = stripped.upper()
    assert upper.startswith("SELECT") or upper.startswith("PRAGMA"), "Metadata SQL must start with SELECT or PRAGMA"


def test_render_snapshot_returns_read_only_sql() -> None:
    adapter = SQLiteAdapter()
    sql = adapter.render_snapshot(SnapshotTemplate())
    _assert_read_only_sql(sql)


def test_render_schema_returns_read_only_sql() -> None:
    adapter = SQLiteAdapter()
    sql = adapter.render_schema(SchemaTemplate())
    _assert_read_only_sql(sql)


def test_render_table_returns_read_only_sql() -> None:
    adapter = SQLiteAdapter()
    sql = adapter.render_table(TableTemplate())
    _assert_read_only_sql(sql)


def test_render_column_returns_read_only_sql() -> None:
    adapter = SQLiteAdapter()
    sql = adapter.render_column(ColumnTemplate())
    _assert_read_only_sql(sql)
