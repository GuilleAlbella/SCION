"""add reasoning_event table

Revision ID: 4d5e6f708192
Revises: 3c4d5e6f7081
Create Date: 2026-02-05 18:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4d5e6f708192"
down_revision: Union[str, None] = "3c4d5e6f7081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create reasoning_event table for persisted TAISA reasoning results."""

    op.create_table(
        "reasoning_event",
        sa.Column("reasoning_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("change_id", sa.Integer(), nullable=True),
        sa.Column("taisa_version", sa.String(), nullable=False),
        sa.Column("classification", sa.String(), nullable=False),
        sa.Column("risk_level", sa.String(), nullable=False),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """Drop reasoning_event table."""

    op.drop_table("reasoning_event")
