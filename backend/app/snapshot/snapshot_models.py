"""Internal data transfer objects for snapshot metadata.

These dataclasses represent engine-agnostic, non-ORM structures that are
used within the snapshot pipeline. They describe the logical content of
schemas, tables, and columns without being tied to SQLAlchemy or any
persistence mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SchemaMetadata:
    """Logical representation of a database schema within a snapshot."""

    schema_name: str


@dataclass
class TableMetadata:
    """Logical representation of a table or view within a schema."""

    schema_name: str
    table_name: str
    object_type: str


@dataclass
class ColumnMetadata:
    """Logical representation of a column within a table or view."""

    schema_name: str
    table_name: str
    column_name: str
    data_type: str
    nullable: bool
    ordinal_position: int
