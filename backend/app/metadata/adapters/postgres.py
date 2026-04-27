"""PostgreSQL adapter for rendering metadata templates into SQL.

This adapter uses information_schema views for read-only metadata queries.
"""

from __future__ import annotations

from app.metadata.adapters.base import BaseAdapter
from app.metadata.templates.snapshot import SnapshotTemplate
from app.metadata.templates.schema import SchemaTemplate
from app.metadata.templates.table import TableTemplate
from app.metadata.templates.column import ColumnTemplate


class PostgresAdapter(BaseAdapter):
    """Render engine-agnostic metadata templates as PostgreSQL-compatible SQL."""

    def render_snapshot(self, template: SnapshotTemplate) -> str:
        """Render a snapshot template.

        For PostgreSQL, this assumes snapshot metadata is stored in an
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
        """Render a schema template using information_schema.schemata.

        information_schema.schemata exposes logical schemas via the
        schema_name column.
        """

        return (
            "SELECT\n"
            "  schema_name\n"
            "FROM information_schema.schemata\n"
            "ORDER BY schema_name"
        )

    def render_table(self, template: TableTemplate) -> str:
        """Render a table template using information_schema.tables.

        information_schema.tables provides table and view metadata; table_type
        is mapped to the logical object_type field.
        """

        return (
            "SELECT\n"
            "  table_schema AS schema_name,\n"
            "  table_name,\n"
            "  table_type AS object_type\n"
            "FROM information_schema.tables\n"
            "WHERE table_type IN ('BASE TABLE', 'VIEW')\n"
            "ORDER BY table_schema, table_name"
        )

    def render_column(self, template: ColumnTemplate) -> str:
        """Render a column template using information_schema.columns.

        information_schema.columns exposes column metadata including type,
        nullability, and ordinal position.
        """

        return (
            "SELECT\n"
            "  table_schema AS schema_name,\n"
            "  table_name,\n"
            "  column_name,\n"
            "  data_type,\n"
            "  (is_nullable = 'YES') AS nullable,\n"
            "  ordinal_position\n"
            "FROM information_schema.columns\n"
            "ORDER BY table_schema, table_name, ordinal_position"
        )
