"""add performance indexes on hot tables

Revision ID: d05a1b2c3d4e
Revises: c94d0e6a7b23
Create Date: 2026-05-05 16:00:00.000000

Why this exists
---------------
Until v1.14, no index existed on the columns SCION's hot read paths filter
by. That was tolerable while databases held demo-scale data (~hundreds of
changes, tens of thousands of columns). On a real customer extract — Rahul's
Transcend dev/test, with 250k change events / 240k tables / 9.8M columns /
337k graph nodes — every diff call became a multi-second affair because
``DiffEngine.compute_diff`` and ``GET /diff/{from}/{to}/details`` each kick
off six full-table scans (schemas + tables + columns × 2 snapshots) plus an
idempotency probe on ``change_event``.

Symptom: a previously-1-second diff between snapshot 1 and 10 took 54 s
once a 250k-change snapshot 11 was loaded into the same database, because
the bloated tables scaled the per-query scan time linearly. Removing
snapshot 11 (and thus shrinking the tables) made the diff fast again,
proving the cause was scan size, not pair-specific query logic.

The ``index=True`` annotations on the ORM models cover fresh databases
created via ``Base.metadata.create_all`` (test fixtures, first-time setups),
but existing production databases need this migration to backfill the
indexes on tables that already exist.

Cost: SQLite ``CREATE INDEX`` is online and a one-shot scan; on a 9.8M-row
``column_snapshot`` it takes ~10–20 s of disk I/O once. The payoff is
permanent: every subsequent diff / graph fetch / autocomplete uses the
index instead of full-scanning.

Idempotent: every index is created with ``IF NOT EXISTS`` semantics via
``inspect()`` lookups, so re-running the migration is safe.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d05a1b2c3d4e"
down_revision: Union[str, None] = "c94d0e6a7b23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (index_name, table_name, [column_names]). Order is intentional: snapshot
# tables first (cheapest, smallest), then graph tables, then change_event
# (largest). If the script is interrupted mid-migration the user can
# inspect partial progress and resume; alembic itself only marks the whole
# revision as applied when ``upgrade()`` returns successfully.
_INDEXES_TO_CREATE: list[tuple[str, str, list[str]]] = [
    # ── Snapshot tables (used by DiffEngine on every pair) ──
    ("ix_schema_snapshot_snapshot_id", "schema_snapshot", ["snapshot_id"]),
    ("ix_table_snapshot_schema_id", "table_snapshot", ["schema_id"]),
    ("ix_column_snapshot_table_id", "column_snapshot", ["table_id"]),
    # ── Graph tables (used by /graph, /lineage, /objects/search?source=graph) ──
    ("ix_graph_node_snapshot", "graph_node", ["snapshot_id"]),
    (
        "ix_graph_node_search",
        "graph_node",
        ["snapshot_id", "schema_name", "object_name"],
    ),
    ("ix_graph_edge_snapshot", "graph_edge", ["snapshot_id"]),
    # ── change_event (largest table; index it last) ──
    (
        "ix_change_event_snapshot_pair",
        "change_event",
        ["snapshot_from", "snapshot_to"],
    ),
    (
        "ix_change_event_object_identifier",
        "change_event",
        ["object_identifier"],
    ),
]


def _existing_index_names(bind, table: str) -> set[str]:
    """Return the set of index names already present on ``table``.

    Used to skip ``CREATE INDEX`` calls that would conflict with indexes
    created by a previous run. We rely on the live SQLAlchemy inspector
    here rather than ``IF NOT EXISTS`` SQL because alembic's ``op.create_index``
    doesn't expose that flag portably across dialects.
    """

    inspector = sa.inspect(bind)
    return {idx["name"] for idx in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for index_name, table, columns in _INDEXES_TO_CREATE:
        existing = _existing_index_names(bind, table)
        if index_name in existing:
            continue
        op.create_index(index_name, table, columns)


def downgrade() -> None:
    """Drop the indexes added by ``upgrade``.

    Symmetric and safe to re-run: missing indexes are simply skipped,
    matching the upgrade's idempotency contract.
    """

    bind = op.get_bind()
    for index_name, table, _columns in reversed(_INDEXES_TO_CREATE):
        existing = _existing_index_names(bind, table)
        if index_name not in existing:
            continue
        op.drop_index(index_name, table_name=table)
