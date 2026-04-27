"""SQLite adapter for rendering metadata templates into SQL.

This adapter targets SQLite's system catalogs and PRAGMAs where appropriate.
All queries are read-only and return logical metadata fields.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.engine import Result

from app.db.engine import engine
from app.metadata.adapters.base import BaseAdapter
from app.metadata.templates.snapshot import SnapshotTemplate
from app.metadata.templates.schema import SchemaTemplate
from app.metadata.templates.table import TableTemplate
from app.metadata.templates.column import ColumnTemplate


class SQLiteAdapter(BaseAdapter):
    """Render engine-agnostic metadata templates as SQLite-compatible SQL."""

    def render_snapshot(self, template: SnapshotTemplate) -> str:
        """Render a snapshot template.

        For SQLite, this assumes snapshot metadata is stored in an application
        table named "snapshot" with the expected logical columns.
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
        """Render a schema template using SQLite's PRAGMA database_list.

        SQLite exposes attached databases via PRAGMA database_list, whose
        "name" column is mapped to the logical schema_name field.
        """

        return (
            "PRAGMA database_list"
        )

    def render_table(self, template: TableTemplate) -> str:
        """Render a table template using SQLite's sqlite_master catalog.

        sqlite_master contains entries for tables and views; its "type" column
        is mapped to the logical object_type field.
        """

        return (
            "SELECT\n"
            "  NULL AS schema_name,\n"
            "  name AS table_name,\n"
            "  type AS object_type\n"
            "FROM sqlite_master\n"
            "WHERE type IN ('table', 'view')\n"
            "ORDER BY table_name"
        )

    def render_column(self, template: ColumnTemplate) -> str:
        """Render a column template.

        SQLite exposes column information via PRAGMA table_info, which operates
        per table. A future layer can specialize this further; for now, this
        query describes the logical shape for a single table, with a
        placeholder to be adapted by higher-level code.
        """

        return (
            "PRAGMA table_info('<table_name>')"
        )

    # Public loader-oriented helpers -------------------------------------------------

    def _execute_sql(self, sql: str) -> List[Dict[str, Any]]:
        """Execute a read-only SQL statement against the shared SQLite engine.

        Returns rows as plain dictionaries. This is a thin helper to keep all
        execution localized and re-usable across the list_* methods.
        """

        with engine.connect() as conn:
            result: Result = conn.exec_driver_sql(sql)
            return [dict(row) for row in result.mappings().all()]

    def list_schemas(self) -> List[Dict[str, Any]]:
        """Return logical schema metadata with canonical keys.

        For SQLite, schemas correspond to attached databases exposed via
        PRAGMA database_list. The "name" column is mapped to schema_name.
        """

        sql = self.render_schema(SchemaTemplate())
        rows = self._execute_sql(sql)
        return [
            {"schema_name": row.get("name", "main")}
            for row in rows
        ]

    def list_tables(self) -> List[Dict[str, Any]]:
        """Return logical table metadata with canonical keys.

        Reuses the existing render_table SQL, which already selects the
        canonical logical fields.
        """

        sql = self.render_table(TableTemplate())
        rows = self._execute_sql(sql)
        return [
            {
                # SQLite's sqlite_master does not carry a schema concept by
                # default; we normalize this to "main" for consistency with
                # list_schemas, which maps the primary database to "main".
                "schema_name": row.get("schema_name") or "main",
                "table_name": row["table_name"],
                "object_type": row["object_type"],
            }
            for row in rows
        ]

    def list_columns(self) -> List[Dict[str, Any]]:
        """Return logical column metadata with canonical keys.

        This implementation iterates over all discovered tables and, for each
        table, queries SQLite's PRAGMA table_info to obtain column-level
        details.
        """

        tables = self.list_tables()
        columns: List[Dict[str, Any]] = []

        with engine.connect() as conn:
            for table in tables:
                table_name = table["table_name"]
                schema_name = table.get("schema_name") or "main"

                pragma_sql = f"PRAGMA table_info('{table_name}')"
                result: Result = conn.exec_driver_sql(pragma_sql)
                for row in result.mappings().all():
                    columns.append(
                        {
                            "schema_name": schema_name,
                            "table_name": table_name,
                            "column_name": row["name"],
                            "data_type": row["type"],
                            "nullable": not bool(row["notnull"]),
                            "ordinal_position": row["cid"],
                        }
                    )

        return columns
