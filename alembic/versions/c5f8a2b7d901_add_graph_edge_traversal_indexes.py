"""Add graph edge traversal indexes.

Revision ID: c5f8a2b7d901
Revises: b49e5f6c7d8e
Create Date: 2026-06-17
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c5f8a2b7d901"
down_revision: Union[str, None] = "b49e5f6c7d8e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES_TO_CREATE: list[tuple[str, str, list[str]]] = [
    (
        "ix_graph_edge_snapshot_source",
        "graph_edge",
        ["snapshot_id", "source_node_id"],
    ),
    (
        "ix_graph_edge_snapshot_target",
        "graph_edge",
        ["snapshot_id", "target_node_id"],
    ),
    (
        "ix_change_event_snapshot_to",
        "change_event",
        ["snapshot_to"],
    ),
]


def _existing_index_names(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {idx["name"] for idx in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for index_name, table, columns in _INDEXES_TO_CREATE:
        if index_name in _existing_index_names(bind, table):
            continue
        op.create_index(index_name, table, columns)


def downgrade() -> None:
    bind = op.get_bind()
    for index_name, table, _columns in reversed(_INDEXES_TO_CREATE):
        if index_name not in _existing_index_names(bind, table):
            continue
        op.drop_index(index_name, table_name=table)
