"""Loader implementation for executing metadata templates via adapters.

This module defines the `SnapshotLoader` class, which is responsible for
coordinating template execution through an injected adapter and normalizing
the raw results into internal data transfer objects. It does not perform any
persistence or business logic; it only shapes the metadata for later stages
of the snapshot pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from app.snapshot.snapshot_models import ColumnMetadata, SchemaMetadata, TableMetadata
from app.snapshot.template_sets import DEFAULT_SNAPSHOT_TEMPLATE_SET


@dataclass
class SnapshotLoader:
    """Load raw metadata required for building a snapshot.

    The loader delegates execution of metadata templates to a provided
    adapter instance. The adapter is expected to expose methods that execute
    the underlying queries and return iterables of dictionaries with
    canonical field names.
    """

    adapter: Any
    template_set: Tuple[str, ...] = DEFAULT_SNAPSHOT_TEMPLATE_SET

    def load(self) -> Dict[str, Any]:
        """Execute metadata templates and return normalized raw metadata.

        The returned dictionary has the following shape::

            {
                "schemas": List[SchemaMetadata],
                "tables": List[TableMetadata],
                "columns": List[ColumnMetadata],
            }

        The adapter is assumed to provide the following call signatures::

            adapter.list_schemas() -> Iterable[dict]
            adapter.list_tables() -> Iterable[dict]
            adapter.list_columns() -> Iterable[dict]

        Each row dictionary must use canonical field names as defined by the
        logical templates (schema_name, table_name, column_name, data_type,
        nullable, ordinal_position, etc.). No defensive checks are performed;
        missing keys will surface as runtime errors.
        """

        raw_schemas: Iterable[Dict[str, Any]] = []
        raw_tables: Iterable[Dict[str, Any]] = []
        raw_columns: Iterable[Dict[str, Any]] = []

        if "list_schemas" in self.template_set:
            raw_schemas = self._call_adapter_method("list_schemas")

        if "list_tables" in self.template_set:
            raw_tables = self._call_adapter_method("list_tables")

        if "list_columns" in self.template_set:
            raw_columns = self._call_adapter_method("list_columns")

        schemas = [
            SchemaMetadata(schema_name=row["schema_name"]) for row in raw_schemas
        ]

        tables = [
            TableMetadata(
                schema_name=row["schema_name"],
                table_name=row["table_name"],
                object_type=row["object_type"],
            )
            for row in raw_tables
        ]

        columns = [
            ColumnMetadata(
                schema_name=row["schema_name"],
                table_name=row["table_name"],
                column_name=row["column_name"],
                data_type=row["data_type"],
                nullable=row["nullable"],
                ordinal_position=row["ordinal_position"],
            )
            for row in raw_columns
        ]

        return {
            "schemas": schemas,
            "tables": tables,
            "columns": columns,
        }

    def _call_adapter_method(self, name: str) -> Iterable[Dict[str, Any]]:
        """Invoke a named template method on the adapter and return its rows.

        This helper keeps all adapter calls in a single place and assumes
        that the adapter provides concrete implementations for the expected
        methods. Any attribute errors are allowed to surface, as the current
        design does not introduce defensive behavior.
        """

        method = getattr(self.adapter, name, None)
        if method is None:
            # Missing template methods are treated as no-op for this loader.
            # This allows template sets to reference operations that are not
            # implemented by a given adapter without failing execution.
            return []
        return method()
