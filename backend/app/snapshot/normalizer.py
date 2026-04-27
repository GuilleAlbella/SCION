"""Engine-agnostic normalization for snapshot metadata extraction.

This module transforms raw query results produced by the metadata runner into
canonical, engine-independent structures that are convenient for persistence
via the repository layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List


@dataclass
class NormalizedColumn:
    """Canonical representation of a column within a table."""

    schema_name: str
    table_name: str
    column_name: str
    data_type: str
    nullable: bool
    ordinal_position: int


@dataclass
class NormalizedTable:
    """Canonical representation of a table or view within a schema."""

    schema_name: str
    table_name: str
    object_type: str
    columns: List[NormalizedColumn]


@dataclass
class NormalizedSchema:
    """Canonical representation of a logical schema in a snapshot."""

    schema_name: str
    tables: List[NormalizedTable]


class SnapshotNormalizer:
    """Normalize raw metadata rows into canonical snapshot structures.

    The normalizer is engine-agnostic: it only relies on the logical field
    names returned by the metadata templates and runner, not on any engine-
    specific details. This keeps persistence concerns separate from catalog
    quirks.
    """

    def normalize(
        self,
        schema_rows: Iterable[Dict[str, object]],
        table_rows: Iterable[Dict[str, object]],
        column_rows: Iterable[Dict[str, object]],
    ) -> List[NormalizedSchema]:
        """Build a hierarchical structure of schemas, tables, and columns.

        The input rows are expected to come from the metadata runner using the
        logical templates, which guarantees a consistent set of field names
        across engines.
        """

        # Index columns by (schema_name, table_name) so that tables can attach
        # their columns in a single pass.
        columns_by_table: Dict[tuple[str, str], List[NormalizedColumn]] = {}
        for row in column_rows:
            schema_name = str(row.get("schema_name"))
            table_name = str(row.get("table_name"))
            column = NormalizedColumn(
                schema_name=schema_name,
                table_name=table_name,
                column_name=str(row.get("column_name")),
                data_type=str(row.get("data_type")),
                nullable=bool(row.get("nullable")),
                ordinal_position=int(row.get("ordinal_position")),
            )
            columns_by_table.setdefault((schema_name, table_name), []).append(column)

        # Build tables and group them by schema.
        tables_by_schema: Dict[str, List[NormalizedTable]] = {}
        for row in table_rows:
            schema_name = str(row.get("schema_name")) if row.get("schema_name") is not None else ""
            table_name = str(row.get("table_name"))
            object_type = str(row.get("object_type"))
            cols = columns_by_table.get((schema_name, table_name), [])
            table = NormalizedTable(
                schema_name=schema_name,
                table_name=table_name,
                object_type=object_type,
                columns=sorted(cols, key=lambda c: c.ordinal_position),
            )
            tables_by_schema.setdefault(schema_name, []).append(table)

        # Finally, construct schemas with their tables.
        schemas: List[NormalizedSchema] = []
        seen_schemas: Dict[str, bool] = {}
        for row in schema_rows:
            schema_name = str(row.get("schema_name"))
            if schema_name in seen_schemas:
                continue
            seen_schemas[schema_name] = True
            tables = tables_by_schema.get(schema_name, [])
            schemas.append(
                NormalizedSchema(
                    schema_name=schema_name,
                    tables=sorted(tables, key=lambda t: t.table_name),
                )
            )

        # Include schemas that may have tables but were not explicitly listed
        # in schema_rows (e.g. engines without a dedicated schema listing).
        for schema_name, tables in tables_by_schema.items():
            if schema_name not in seen_schemas:
                schemas.append(
                    NormalizedSchema(
                        schema_name=schema_name,
                        tables=sorted(tables, key=lambda t: t.table_name),
                    )
                )

        return sorted(schemas, key=lambda s: s.schema_name)
