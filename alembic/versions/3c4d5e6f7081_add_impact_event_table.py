"""add impact_event table

Revision ID: 3c4d5e6f7081
Revises: 2b3c4d5e6f70
Create Date: 2026-02-05 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3c4d5e6f7081"
down_revision: Union[str, None] = "2b3c4d5e6f70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create impact_event table for persisted impact analysis events."""

    op.create_table(
        "impact_event",
        sa.Column("impact_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("change_id", sa.Integer(), nullable=False),
        sa.Column("impacted_node_id", sa.Integer(), nullable=False),
        sa.Column("impact_level", sa.String(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop impact_event table."""

    op.drop_table("impact_event")
