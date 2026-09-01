"""graph: add case-insensitive functional index for root resolution

Revision ID: c2d3e4f5a6b7
Revises: b3f2e1d0c9a8
Create Date: 2026-09-01

§2.6 Graph engine perf -- _resolve_root() in graph.py uses
func.lower(schema_name) / func.lower(object_name) in its WHERE clause.
The existing ix_graph_node_search index is defined on the raw column
values, so the query planner cannot use it for those lower()-wrapped
predicates and falls back to a full snapshot scan (up to 337k rows).

This migration adds a *functional* index on
  (snapshot_id, lower(schema_name), lower(object_name))
turning every root-resolution call in GET /graph/focus into an index seek.

Both SQLite (>= 3.38, Feb 2022) and PostgreSQL support functional indexes
natively.  We use raw DDL because SQLAlchemy's op.create_index() does not
accept expression columns.  IF NOT EXISTS makes the migration idempotent
without an extra inspect() round-trip.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b3f2e1d0c9a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "ix_graph_node_search_ci"
_DDL_CREATE = (
    "CREATE INDEX IF NOT EXISTS ix_graph_node_search_ci "
    "ON graph_node (snapshot_id, lower(schema_name), lower(object_name))"
)
_DDL_DROP = "DROP INDEX IF EXISTS ix_graph_node_search_ci"


def upgrade() -> None:
    op.execute(_DDL_CREATE)


def downgrade() -> None:
    op.execute(_DDL_DROP)
