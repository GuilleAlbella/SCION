"""extend_graph_edge_for_system_graph

Revision ID: ea1f255a8cd9
Revises: cde1c1f6c77d
Create Date: 2026-02-09 09:14:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ea1f255a8cd9"
down_revision: Union[str, None] = "cde1c1f6c77d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "graph_edge",
        sa.Column("from_node_uid", sa.String(), nullable=True),
    )
    op.add_column(
        "graph_edge",
        sa.Column("to_node_uid", sa.String(), nullable=True),
    )
    op.add_column(
        "graph_edge",
        sa.Column("edge_type", sa.String(), nullable=True),
    )
    op.add_column(
        "graph_edge",
        sa.Column("metadata", sa.JSON(), nullable=True),
    )
    op.add_column(
        "graph_edge",
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("graph_edge", "created_at")
    op.drop_column("graph_edge", "metadata")
    op.drop_column("graph_edge", "edge_type")
    op.drop_column("graph_edge", "to_node_uid")
    op.drop_column("graph_edge", "from_node_uid")
