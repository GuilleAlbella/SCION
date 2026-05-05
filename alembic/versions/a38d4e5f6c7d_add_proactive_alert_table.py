"""add proactive_alert table

Revision ID: a38d4e5f6c7d
Revises: f27c3d4e5f6b
Create Date: 2026-05-05 21:00:00.000000

The /alerts endpoint moved from "compute on every request" (load all
graph_node + graph_edge rows for the snapshot, walk in Python) to
"compute once during post-ingest, persist, read on demand". This
migration creates the table that holds the persisted output.

Idempotent: skip when the table already exists.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a38d4e5f6c7d"
down_revision: Union[str, None] = "f27c3d4e5f6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "proactive_alert" in inspector.get_table_names():
        return

    op.create_table(
        "proactive_alert",
        sa.Column("alert_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("alert_type", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("object_identifier", sa.String(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_proactive_alert_snapshot",
        "proactive_alert",
        ["snapshot_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "proactive_alert" not in inspector.get_table_names():
        return
    op.drop_index("ix_proactive_alert_snapshot", table_name="proactive_alert")
    op.drop_table("proactive_alert")
