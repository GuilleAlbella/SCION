"""add extract_run_id column to snapshot

Revision ID: a72b8c4f9d31
Revises: f1a8b3c5d207
Create Date: 2026-04-29 14:30:00.000000

Adds a dedicated `extract_run_id` column on the `snapshot` table so the
data-dictionary ingest pipeline (v1.12.00) can do an exact-match
idempotency lookup instead of grepping `description LIKE '%...%'`.

Why this change
- The original v1.12 implementation embedded `extract_run_id=...` in
  `snapshot.description` and used a LIKE query to detect re-imports.
  That works but is fragile: any change to the description format
  breaks idempotency silently.
- A dedicated column is one indexed lookup; LIKE on a free-text field
  is a sequential scan and not an index a SQLite or Postgres planner
  can use efficiently.
- The column is nullable because pre-existing snapshots (parser-import
  + demo seed) don't have an extract_run_id. New rows from
  `dict_persister.py` will populate it.

Backward compatibility
- The persister still writes `extract_run_id=...` into the description
  string for one more release so older clients with cached descriptions
  don't see a regression. Both signals are accepted on read; new writes
  use the column. We can drop the description-side hint in v1.14.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic identifiers.
revision: str = "a72b8c4f9d31"
down_revision: Union[str, None] = "f1a8b3c5d207"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nullable `extract_run_id` column with a non-unique index.

    Index keeps idempotency lookups O(log n) regardless of how many
    snapshots accumulate. Not unique because:
      - parser-import snapshots have NULL here and SQLite treats
        multiple NULLs as distinct, which Postgres also does — fine.
      - in theory two customers could submit the same string; we'd
        rather surface that as a soft conflict in the persister than
        a hard DB error. Uniqueness should be on
        `(source_system, extract_run_id)` and even that is best
        enforced in code (we want a clear "already imported" message,
        not a 500).
    """
    with op.batch_alter_table("snapshot") as batch:
        batch.add_column(sa.Column("extract_run_id", sa.String(), nullable=True))
        batch.create_index(
            "ix_snapshot_extract_run_id",
            ["extract_run_id"],
            unique=False,
        )


def downgrade() -> None:
    """Drop the column and index."""
    with op.batch_alter_table("snapshot") as batch:
        batch.drop_index("ix_snapshot_extract_run_id")
        batch.drop_column("extract_run_id")
