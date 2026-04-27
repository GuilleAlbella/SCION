"""Structural hashing for snapshot fingerprinting.

Produces a deterministic SHA-256 hash of a snapshot's structural state
(schemas, tables, columns with types). Two snapshots with identical
structure produce the same hash, enabling fast equality checks without
running a full diff.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot


def compute_structural_hash(snapshot_id: int) -> str:
    """Compute a SHA-256 hash of the structural state of a snapshot."""

    with Session(engine) as session:
        schemas = session.scalars(
            select(SchemaSnapshot.schema_name)
            .where(SchemaSnapshot.snapshot_id == snapshot_id)
            .order_by(SchemaSnapshot.schema_name)
        ).all()

        tables = session.execute(
            select(
                SchemaSnapshot.schema_name,
                TableSnapshot.table_name,
                TableSnapshot.object_type,
            )
            .join(TableSnapshot, TableSnapshot.schema_id == SchemaSnapshot.schema_id)
            .where(SchemaSnapshot.snapshot_id == snapshot_id)
            .order_by(SchemaSnapshot.schema_name, TableSnapshot.table_name)
        ).all()

        columns = session.execute(
            select(
                SchemaSnapshot.schema_name,
                TableSnapshot.table_name,
                ColumnSnapshot.column_name,
                ColumnSnapshot.data_type,
                ColumnSnapshot.nullable,
                ColumnSnapshot.ordinal_position,
            )
            .join(TableSnapshot, TableSnapshot.schema_id == SchemaSnapshot.schema_id)
            .join(ColumnSnapshot, ColumnSnapshot.table_id == TableSnapshot.table_id)
            .where(SchemaSnapshot.snapshot_id == snapshot_id)
            .order_by(
                SchemaSnapshot.schema_name,
                TableSnapshot.table_name,
                ColumnSnapshot.ordinal_position,
            )
        ).all()

    # Determinism is critical: the whole point of this hash is that two
    # structurally-identical snapshots produce the same digest. Every query
    # above uses ORDER BY to enforce a canonical ordering, and we never
    # include volatile fields like snapshot_id, timestamps, or row counts.
    # Build deterministic string representation
    parts = []
    for s in schemas:
        parts.append(f"S:{s}")
    for schema, table, obj_type in tables:
        parts.append(f"T:{schema}.{table}:{obj_type}")
    for schema, table, col, dtype, nullable, pos in columns:
        parts.append(f"C:{schema}.{table}.{col}:{dtype}:{nullable}:{pos}")

    # Newline separation keeps the hashed representation human-debuggable
    # (you can print `content` and diff two snapshots by eye if needed).
    content = "\n".join(parts)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
