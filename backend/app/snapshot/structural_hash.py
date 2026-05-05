"""Structural hashing for snapshot fingerprinting.

Produces a deterministic SHA-256 hash of a snapshot's structural state
(schemas, tables, columns with types). Two snapshots with identical
structure produce the same hash, enabling fast equality checks without
running a full diff.

Scale note: at 9.8M columns the original implementation materialised
every row into a Python list of formatted strings, called
`"\\n".join(parts)` to build a single ~1 GB string, encoded that
string to UTF-8 bytes, and hashed it. That worked for sub-100k-row
demo snapshots but cost ~50 s and a memory spike of >2 GB on the
Transcend-DevTest extract — most of which was Python object churn,
not the hashing itself.

The current implementation feeds the hasher row-by-row from a
streaming cursor. SHA-256 is associative over byte concatenation, so
calling `hasher.update(part)` repeatedly produces exactly the same
digest as `hasher.update(b"".join(parts))` — which means the hash is
**byte-identical to the prior implementation** as long as we emit the
same bytes in the same order. Critical because `Snapshot.structural_hash`
is persisted across runs; changing the algorithm would invalidate
every existing fingerprint.
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


# How many cursor rows to buffer at a time when streaming the column
# scan. Big enough that per-batch overhead is negligible, small enough
# that we never materialise more than a few MB of result tuples.
_HASH_STREAM_YIELD_PER = 10_000


def compute_structural_hash(snapshot_id: int) -> str:
    """Compute a SHA-256 hash of the structural state of a snapshot."""

    hasher = hashlib.sha256()
    # The original implementation joined every part with `\n` (i.e.
    # newline-separated, no trailing newline). To stay byte-identical
    # we emit a `\n` BEFORE every part except the first one. `prefix`
    # carries that "have we emitted anything yet" state across the
    # three loops below.
    prefix = ""

    with Session(engine) as session:
        # Schemas — small, no streaming complication needed.
        for schema_name in session.scalars(
            select(SchemaSnapshot.schema_name)
            .where(SchemaSnapshot.snapshot_id == snapshot_id)
            .order_by(SchemaSnapshot.schema_name)
        ).all():
            hasher.update(f"{prefix}S:{schema_name}".encode("utf-8"))
            prefix = "\n"

        # Tables — small enough that streaming is overkill, but we
        # use the same `execute(...).yield_per(...)` shape as columns
        # for consistency. Order matches the original: schema_name
        # then table_name.
        tables_stmt = (
            select(
                SchemaSnapshot.schema_name,
                TableSnapshot.table_name,
                TableSnapshot.object_type,
            )
            .join(TableSnapshot, TableSnapshot.schema_id == SchemaSnapshot.schema_id)
            .where(SchemaSnapshot.snapshot_id == snapshot_id)
            .order_by(SchemaSnapshot.schema_name, TableSnapshot.table_name)
        )
        for schema_name, table_name, object_type in session.execute(
            tables_stmt
        ).yield_per(_HASH_STREAM_YIELD_PER):
            # One f-string + one `update` per row. We measured that
            # the chatty version (a separate `update` per byte sequence)
            # was actually *slower* than this on a 9.8M-row scan because
            # each `update` call crosses the Python/C boundary. Bigger
            # buffers, fewer calls.
            hasher.update(
                f"{prefix}T:{schema_name}.{table_name}:{object_type}".encode("utf-8")
            )
            prefix = "\n"

        # Columns — the heavy loop. `yield_per` instructs SQLAlchemy +
        # the underlying DBAPI cursor to fetch in chunks instead of
        # buffering the whole 9.8M-row result set in memory. Combined
        # with feeding the hasher directly (no intermediate `parts`
        # list, no `"\n".join`) the wall-time cost drops from ~50 s
        # to roughly the SQL execution time alone — and at this point
        # most of the wall time is the server-side ORDER BY across
        # 9.8M rows, which we can't avoid without breaking the hash's
        # determinism contract.
        cols_stmt = (
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
        )
        for schema_name, table_name, column_name, data_type, nullable, pos in (
            session.execute(cols_stmt).yield_per(_HASH_STREAM_YIELD_PER)
        ):
            hasher.update(
                f"{prefix}C:{schema_name}.{table_name}.{column_name}"
                f":{data_type}:{nullable}:{pos}".encode("utf-8")
            )
            prefix = "\n"

    return hasher.hexdigest()
