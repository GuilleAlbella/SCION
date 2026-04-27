"""add change_event table

Revision ID: 1a2b3c4d5e6f
Revises: 09a9712f5623
Create Date: 2026-02-05 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "09a9712f5623"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create change_event table for persisted diff events.

    This migration formalizes the schema already used by the Diff Engine v5.5
    without changing runtime behaviour.
    """

    op.create_table(
        "change_event",
        sa.Column("change_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_from", sa.Integer(), nullable=False),
        sa.Column("snapshot_to", sa.Integer(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("object_identifier", sa.String(), nullable=False),
        sa.Column("change_type", sa.String(), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop change_event table."""

    op.drop_table("change_event")
