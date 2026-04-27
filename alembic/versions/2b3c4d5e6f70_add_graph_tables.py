"""add graph_node and graph_edge tables

Revision ID: 2b3c4d5e6f70
Revises: 1a2b3c4d5e6f
Create Date: 2026-02-05 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2b3c4d5e6f70"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create graph_node and graph_edge tables for technical graph persistence.

    This migration introduces storage for the graph engine without adding
    foreign keys, indexes, or behavioural logic.
    """

    op.create_table(
        "graph_node",
        sa.Column("node_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("object_name", sa.String(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
    )

    op.create_table(
        "graph_edge",
        sa.Column("edge_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_node_id", sa.Integer(), nullable=False),
        sa.Column("target_node_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.String(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    """Drop graph_node and graph_edge tables."""

    op.drop_table("graph_edge")
    op.drop_table("graph_node")
