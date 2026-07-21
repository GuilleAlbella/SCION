"""baseline_snapshot_fk — add missing FK constraint for §2.2.

The incremental loading migration (f6a7b8c9d0e1) added baseline_snapshot_id
as a plain Integer column but did not create the FK constraint in the DB.
The ORM model has ForeignKey("snapshot.snapshot_id") but without this
migration Postgres does not enforce referential integrity on that column.

This migration adds the FK constraint retroactively.  It is safe to apply
on an existing database because:
  - The column already exists (no schema change needed).
  - The LIFO delete constraint in the API ensures no dangling references
    can exist: you can only delete the latest snapshot, so a baseline is
    never deleted while its incrementals still exist.

Revision: b8c9d0e1f2a3
"""
from __future__ import annotations

from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_snapshot_baseline_snapshot_id",
        "snapshot",
        "snapshot",
        ["baseline_snapshot_id"],
        ["snapshot_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_snapshot_baseline_snapshot_id",
        "snapshot",
        type_="foreignkey",
    )
