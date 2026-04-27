"""Snapshot validation utilities.

This module contains structural integrity checks that are applied to a
persisted snapshot before it is considered valid. The checks operate purely
on the database state and do not depend on adapter-specific behaviour.
"""

from __future__ import annotations

from typing import Tuple, Type

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.column_snapshot import ColumnSnapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.snapshot import Snapshot
from app.db.models.table_snapshot import TableSnapshot


def validate_snapshot(
    *,
    session: Session,
    snapshot: Snapshot,
    template_set: Tuple[str, ...],
    error_cls: Type[Exception],
) -> None:
    """Validate that a persisted snapshot is structurally coherent.

    The function inspects only the database state for the given ``snapshot``
    and raises ``error_cls`` if any integrity rule is violated. If no
    exception is raised, the snapshot is considered valid.
    """

    if snapshot.snapshot_id is None or snapshot.snapshot_time is None:
        raise error_cls(
            "Snapshot validation failed: snapshot record is incomplete.",
        )

    snapshot_id = snapshot.snapshot_id

    # Collect schemas for this snapshot when schema-level templates are active.
    schema_ids: set[int] = set()
    if "list_schemas" in template_set:
        schemas = session.scalars(
            select(SchemaSnapshot).where(SchemaSnapshot.snapshot_id == snapshot_id)
        ).all()
        if not schemas:
            raise error_cls(
                "Snapshot validation failed: no schemas persisted for snapshot.",
            )
        schema_ids = {s.schema_id for s in schemas}

    # Table-level validation builds on top of schemas when table templates exist.
    table_ids: set[int] = set()
    if "list_tables" in template_set:
        if not schema_ids and "list_schemas" in template_set:
            # Schema templates were active but no schemas were found; this
            # condition is already handled above. This branch simply guards
            # against inconsistent invocation.
            raise error_cls(
                "Snapshot validation failed: table validation requires schemas.",
            )

        tables = session.scalars(
            select(TableSnapshot).where(TableSnapshot.schema_id.in_(schema_ids))
        ).all()
        if not tables:
            raise error_cls(
                "Snapshot validation failed: no tables persisted for snapshot.",
            )
        table_ids = {t.table_id for t in tables}

    # Column-level validation is conditional and allows zero columns. When
    # columns exist, they must reference tables from this snapshot and have a
    # non-null ordinal_position.
    if "list_columns" in template_set and table_ids:
        columns = session.scalars(
            select(ColumnSnapshot).where(ColumnSnapshot.table_id.in_(table_ids))
        ).all()

        for col in columns:
            if col.table_id not in table_ids:
                raise error_cls(
                    "Snapshot validation failed: column references unknown table.",
                )
            if col.ordinal_position is None:
                raise error_cls(
                    "Snapshot validation failed: column ordinal_position is null.",
                )
