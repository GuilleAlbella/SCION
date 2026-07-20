"""graph perf: merge heads + add change_event composite index

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6, d61e9f7a2b34
Create Date: 2026-07-20 00:00:00.000000

Merges the two open Alembic branch-tips and adds a composite index on
change_event(snapshot_to, object_identifier) that the Intelligence and
Timeline pages use when filtering by object name within a snapshot.

Previously only individual single-column indexes existed:
  - ix_change_event_snapshot_to     (snapshot_to)
  - ix_change_event_object_identifier (object_identifier)

The composite index lets the DB satisfy
  WHERE snapshot_to = :s AND object_identifier = :q
with a single b-tree lookup instead of a full-scan + filter.
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = ("f1a2b3c4d5e6", "d61e9f7a2b34")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_change_event_snapshot_to_object",
        "change_event",
        ["snapshot_to", "object_identifier"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_change_event_snapshot_to_object",
        table_name="change_event",
    )
