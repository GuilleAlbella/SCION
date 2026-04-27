"""Smoke tests for the metadata runner read-only behavior.

These tests validate that:
- Read-only metadata queries can be executed successfully.
- Non-SELECT / non-PRAGMA statements are rejected.
- Results from successful executions are iterable.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine

from app.metadata.runner.engine import SqlAlchemyExecutionEngine
from app.metadata.runner.runner import MetadataRunner
from app.metadata.templates.schema import SchemaTemplate


def _create_sqlite_engine() -> Any:
    """Create a SQLAlchemy engine pointing at the existing demo SQLite DB.

    The database file "kalido_lite.db" is assumed to exist and to have been
    initialized by Alembic migrations.
    """

    return create_engine("sqlite:///kalido_lite.db")


def test_select_queries_execute_successfully() -> None:
    """A simple schema template should execute successfully in read-only mode."""

    engine = _create_sqlite_engine()
    exec_engine = SqlAlchemyExecutionEngine(engine)
    runner = MetadataRunner("sqlite", exec_engine)

    template = SchemaTemplate()
    rows = runner.run_schema(template)

    # The runner must return an iterable collection of row mappings.
    assert hasattr(rows, "__iter__"), "Result set must be iterable"
    # Iterating should not raise, even if the result set is empty.
    list(rows)


def test_non_select_sql_is_rejected_by_execution_engine() -> None:
    """The execution engine must reject non-SELECT / non-PRAGMA statements."""

    engine = _create_sqlite_engine()
    exec_engine = SqlAlchemyExecutionEngine(engine)

    with pytest.raises(ValueError):
        exec_engine.execute("UPDATE some_table SET x = 1")


def test_non_select_sql_is_rejected_by_runner_validation() -> None:
    """The runner-level validation must also reject non-read-only SQL."""

    # Use the internal validation helper to ensure it enforces read-only usage.
    with pytest.raises(ValueError):
        MetadataRunner._validate_read_only("DELETE FROM some_table")
