"""add index on impact_event(change_id, snapshot_id)

Revision ID: f1a2b3c4d5e6
Revises: ea1f255a8cd9
Create Date: 2026-07-08 00:00:00.000000

The impact_event table previously had no indexes. The idempotency check
in impact_persister queries by (change_id, snapshot_id) on every single-
change impact request — without an index this is a full table scan that
grows with every analysis run.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "ea1f255a8cd9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_impact_event_change_snapshot",
        "impact_event",
        ["change_id", "snapshot_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_impact_event_change_snapshot", table_name="impact_event")
