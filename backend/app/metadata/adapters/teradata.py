"""Teradata adapter for rendering metadata templates into SQL.

This adapter uses DBC metadata views such as TablesV and ColumnsV.
All queries are read-only and limited to metadata structures.
"""

from __future__ import annotations

from app.metadata.adapters.base import BaseAdapter
from app.metadata.templates.snapshot import SnapshotTemplate
from app.metadata.templates.schema import SchemaTemplate
from app.metadata.templates.table import TableTemplate
from app.metadata.templates.column import ColumnTemplate


class TeradataAdapter(BaseAdapter):
    """Render engine-agnostic metadata templates as Teradata-compatible SQL."""

    def render_snapshot(self, template: SnapshotTemplate) -> str:
        """Render a snapshot template.

        For Teradata, this assumes snapshot metadata is stored in an
        application table named "snapshot" with the expected logical columns.
        """

        return (
            "SELECT\n"
            "  snapshot_time,\n"
            "  source_system,\n"
            "  description\n"
            "FROM snapshot\n"
            "ORDER BY snapshot_time DESC"
        )

    def render_schema(self, template: SchemaTemplate) -> str:
        """Render a schema template using DBC.DatabasesV.

        DatabasesV exposes Teradata databases, which are mapped to the
        logical schema_name field.
        """

        return (
            "SELECT\n"
            "  DatabaseName AS schema_name\n"
            "FROM DBC.DatabasesV\n"
            "ORDER BY DatabaseName"
        )

    def render_table(self, template: TableTemplate) -> str:
        """Render a table template using DBC.TablesV.

        TablesV provides table and view metadata; TableKind is mapped to the
        logical object_type field.
        """

        return (
            "SELECT\n"
            "  DatabaseName AS schema_name,\n"
            "  TableName AS table_name,\n"
            "  TableKind AS object_type\n"
            "FROM DBC.TablesV\n"
            "WHERE TableKind IN ('T', 'V')\n"
            "ORDER BY DatabaseName, TableName"
        )

    def render_column(self, template: ColumnTemplate) -> str:
        """Render a column template using DBC.ColumnsV.

        ColumnsV exposes column-level metadata including type, nullability,
        and column ordering.
        """

        return (
            "SELECT\n"
            "  DatabaseName AS schema_name,\n"
            "  TableName AS table_name,\n"
            "  ColumnName AS column_name,\n"
            "  ColumnType AS data_type,\n"
            "  Nullable AS nullable,\n"
            "  ColumnId AS ordinal_position\n"
            "FROM DBC.ColumnsV\n"
            "ORDER BY DatabaseName, TableName, ColumnId"
        )
