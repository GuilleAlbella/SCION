"""add_created_at_to_graph_node

Revision ID: cde1c1f6c77d
Revises: 27737b1267fe
Create Date: 2026-02-09 08:30:41.781742

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "cde1c1f6c77d"
down_revision: Union[str, None] = "27737b1267fe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "graph_node",
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("graph_node", "created_at")