"""backfill columns added to ORM but never migrated

Revision ID: e16b2c3d4f5a
Revises: d05a1b2c3d4e
Create Date: 2026-05-05 17:00:00.000000

Why this exists
---------------
Five columns were added to ORM models over the course of v0.x→v1.14 but
never received Alembic migrations. The dev-side path
(``Base.metadata.create_all`` via the old ``bootstrap_sqlite_db.py``)
silently created them, so demos and the developer's local DB always had
them. The ``alembic upgrade head`` path didn't, which is what bit Helton
and what the new ``test_schema_parity.py`` flagged as drift on its first
run.

Columns being backfilled (all nullable so we can add them to populated
tables without a default-value dance):

  - ``snapshot.structural_hash``   (String) — added in the snapshot-engine
    overhaul; lets repeated dict-imports detect "same content, skip".
  - ``snapshot.object_count``      (Integer) — convenience cache populated
    by the ingest pipeline.
  - ``change_event.severity``      (String) — diff classifier output
    (HIGH / MEDIUM / LOW). Used by the Changes table KPIs.
  - ``change_event.is_breaking``   (Boolean) — independent flag from
    severity; drives the Breaking badges and breaking-only filter.
  - ``impact_event.impact_score``  (Float) — quantitative impact weight
    used by the Impact Analysis blast radius.

Idempotency
-----------
Every column add is guarded by an inspector lookup. Existing dev DBs that
already have the columns (because ``Base.metadata.create_all`` ran at
some point) are no-ops on this migration; fresh DBs created by
``alembic upgrade head`` get the columns added properly.

We use ``op.batch_alter_table`` so the same migration works on both
SQLite (where ALTER ADD COLUMN has limitations historically and batch
mode rebuilds the table when needed) and Postgres (where it's a no-op
wrapper).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e16b2c3d4f5a"
down_revision: Union[str, None] = "d05a1b2c3d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column_name, sa.Column factory). Factories — not column instances —
# because Column is mutable and SQLAlchemy attaches state to it the first
# time it's added; reusing a single Column across upgrade and downgrade
# was producing "already attached to Table" errors during testing.
_BACKFILLS: list[tuple[str, str]] = [
    ("snapshot", "structural_hash"),
    ("snapshot", "object_count"),
    ("change_event", "severity"),
    ("change_event", "is_breaking"),
    ("impact_event", "impact_score"),
]


def _column_factory(table: str, name: str) -> sa.Column:
    """Return a fresh ``sa.Column`` for ``(table, name)``.

    Centralised so the upgrade and downgrade paths agree on shape.
    """
    if (table, name) == ("snapshot", "structural_hash"):
        return sa.Column("structural_hash", sa.String(), nullable=True)
    if (table, name) == ("snapshot", "object_count"):
        return sa.Column("object_count", sa.Integer(), nullable=True)
    if (table, name) == ("change_event", "severity"):
        return sa.Column("severity", sa.String(), nullable=True)
    if (table, name) == ("change_event", "is_breaking"):
        return sa.Column("is_breaking", sa.Boolean(), nullable=True)
    if (table, name) == ("impact_event", "impact_score"):
        return sa.Column("impact_score", sa.Float(), nullable=True)
    raise KeyError(f"Unknown backfill target: {(table, name)}")


def _existing_column_names(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    for table, column in _BACKFILLS:
        existing = _existing_column_names(bind, table)
        if column in existing:
            continue
        op.add_column(table, _column_factory(table, column))


def downgrade() -> None:
    """Drop the backfilled columns.

    SQLite < 3.35 doesn't support ``DROP COLUMN`` directly, so alembic
    rebuilds the table via ``batch_alter_table``. The downgrade path is
    rarely exercised in practice — this exists so the migration is
    symmetric and reversible in CI.
    """
    bind = op.get_bind()
    for table, column in reversed(_BACKFILLS):
        existing = _existing_column_names(bind, table)
        if column not in existing:
            continue
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column(column)
