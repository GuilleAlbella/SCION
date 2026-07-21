"""object_entity_fk_cascade — add ON DELETE CASCADE to lifecycle FK columns.

The integration_model migration (c3d4e5f6a7b8) created first_seen_snapshot_id
and last_seen_snapshot_id without an ondelete action, defaulting to RESTRICT in
Postgres.  This means delete_snapshot raises a ForeignKeyViolation for any
snapshot that is referenced by at least one object_entity row (i.e. every
snapshot after the first entity-resolve pass).

Fix: replace both FK constraints with ON DELETE CASCADE.  When a snapshot is
deleted, entity rows that reference it as first_seen or last_seen are
automatically removed.  This is safe because:

  - The LIFO constraint in delete_snapshot (only the latest snapshot can be
    deleted) ensures we never delete a historical snapshot that is the
    first_seen anchor for entities still actively seen in newer snapshots.
  - The entity resolver is idempotent: the next ingest re-creates any entity
    rows removed by the cascade.

Postgres auto-names these constraints as
  object_entity_first_seen_snapshot_id_fkey
  object_entity_last_seen_snapshot_id_fkey
which is what we drop and re-create here.

Revision: c9d0e1f2a3b4
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite does not support named FK constraints — skip; demo DB doesn't
    # enforce FKs and the CASCADE is only meaningful in Postgres.
    if op.get_bind().dialect.name == "sqlite":
        return

    # Drop auto-named constraints created by c3d4e5f6a7b8
    op.drop_constraint(
        "object_entity_first_seen_snapshot_id_fkey",
        "object_entity",
        type_="foreignkey",
    )
    op.drop_constraint(
        "object_entity_last_seen_snapshot_id_fkey",
        "object_entity",
        type_="foreignkey",
    )
    # Re-create with CASCADE so deleting a snapshot cleans up entity lifecycle rows
    op.create_foreign_key(
        "fk_object_entity_first_seen",
        "object_entity",
        "snapshot",
        ["first_seen_snapshot_id"],
        ["snapshot_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_object_entity_last_seen",
        "object_entity",
        "snapshot",
        ["last_seen_snapshot_id"],
        ["snapshot_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return

    op.drop_constraint("fk_object_entity_last_seen", "object_entity", type_="foreignkey")
    op.drop_constraint("fk_object_entity_first_seen", "object_entity", type_="foreignkey")
    op.create_foreign_key(
        "object_entity_last_seen_snapshot_id_fkey",
        "object_entity", "snapshot",
        ["last_seen_snapshot_id"], ["snapshot_id"],
    )
    op.create_foreign_key(
        "object_entity_first_seen_snapshot_id_fkey",
        "object_entity", "snapshot",
        ["first_seen_snapshot_id"], ["snapshot_id"],
    )
