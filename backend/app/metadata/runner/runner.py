"""Metadata runner that orchestrates templates, adapters, and execution.

This layer is responsible for:
- Selecting the correct adapter for a given engine name.
- Rendering engine-agnostic templates into SQL strings using adapters.
- Enforcing read-only semantics before delegating to the execution engine.
- Executing SQL using SQLAlchemy Core via an ExecutionEngine.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.metadata.adapters import BaseAdapter, PostgresAdapter, SQLiteAdapter, TeradataAdapter
from app.metadata.runner.engine import ExecutionEngine
from app.metadata.templates.column import ColumnTemplate
from app.metadata.templates.schema import SchemaTemplate
from app.metadata.templates.snapshot import SnapshotTemplate
from app.metadata.templates.table import TableTemplate


class MetadataRunner:
    """Run logical metadata templates against a specific database engine.

    The runner remains engine-agnostic by selecting an adapter purely based on
    a simple engine name string, rather than inspecting runtime connection
    details, and by delegating all SQL rendering to the adapter layer.
    """

    def __init__(self, engine_name: str, execution_engine: ExecutionEngine) -> None:
        """Create a new metadata runner for a given engine name.

        The engine_name value is used to select which adapter will be used to
        render SQL; no runtime detection or inspection of the SQLAlchemy Engine
        is performed here.
        """

        self._adapter = self._select_adapter(engine_name)
        self._execution_engine = execution_engine

    @staticmethod
    def _select_adapter(engine_name: str) -> BaseAdapter:
        """Select an adapter based on a simple engine name string.

        This avoids tightly coupling the runner to SQLAlchemy's internal
        dialect structures while still allowing different engines to be
        supported.
        """

        normalized = engine_name.strip().lower()
        if normalized == "sqlite":
            return SQLiteAdapter()
        if normalized in {"postgres", "postgresql"}:
            return PostgresAdapter()
        if normalized == "teradata":
            return TeradataAdapter()

        raise ValueError(f"Unsupported engine name for metadata runner: {engine_name!r}")

    def run_snapshot(self, template: SnapshotTemplate) -> List[Dict[str, Any]]:
        """Render and execute a snapshot template as a read-only query."""

        sql = self._adapter.render_snapshot(template)
        self._validate_read_only(sql)
        return self._execution_engine.execute(sql)

    def run_schema(self, template: SchemaTemplate) -> List[Dict[str, Any]]:
        """Render and execute a schema template as a read-only query."""

        sql = self._adapter.render_schema(template)
        self._validate_read_only(sql)
        return self._execution_engine.execute(sql)

    def run_table(self, template: TableTemplate) -> List[Dict[str, Any]]:
        """Render and execute a table template as a read-only query."""

        sql = self._adapter.render_table(template)
        self._validate_read_only(sql)
        return self._execution_engine.execute(sql)

    def run_column(self, template: ColumnTemplate) -> List[Dict[str, Any]]:
        """Render and execute a column template as a read-only query."""

        sql = self._adapter.render_column(template)
        self._validate_read_only(sql)
        return self._execution_engine.execute(sql)

    @staticmethod
    def _validate_read_only(sql: str) -> None:
        """Ensure that the rendered SQL is read-only before execution.

        The runner validates that statements start with SELECT or PRAGMA,
        which are used for metadata inspection on common engines, and refuses
        to run anything else to prevent unintended writes or DDL.
        """

        stripped = sql.lstrip()
        lowered = stripped.lower()
        if not (lowered.startswith("select") or lowered.startswith("pragma")):
            raise ValueError("Metadata runner only allows read-only SELECT/PRAGMA statements.")
