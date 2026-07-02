"""Add snapshot_id to usage_event.

usage_event previously had no link back to the snapshot it was imported
alongside. That meant DELETE /snapshots/{id} couldn't cascade-delete a
snapshot's usage rows (there was nothing to filter on), and re-importing
the same PDCR Object Usage file for a snapshot silently duplicated rows
instead of being detected as a re-run.

Revision ID: d61e9f7a2b34
Revises: c5f8a2b7d901
Create Date: 2026-07-01
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d61e9f7a2b34"
down_revision: Union[str, None] = "c5f8a2b7d901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("usage_event")}
    if "snapshot_id" not in columns:
        op.add_column(
            "usage_event", sa.Column("snapshot_id", sa.Integer(), nullable=True)
        )
    indexes = {idx["name"] for idx in inspector.get_indexes("usage_event")}
    if "ix_usage_event_snapshot_id" not in indexes:
        op.create_index(
            "ix_usage_event_snapshot_id", "usage_event", ["snapshot_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {idx["name"] for idx in inspector.get_indexes("usage_event")}
    if "ix_usage_event_snapshot_id" in indexes:
        op.drop_index("ix_usage_event_snapshot_id", table_name="usage_event")
    columns = {c["name"] for c in inspector.get_columns("usage_event")}
    if "snapshot_id" in columns:
        op.drop_column("usage_event", "snapshot_id")
