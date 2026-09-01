"""add snapshot_type for incremental loading

Revision ID: 0418f861635f
Revises: c9d0e1f2a3b4
Create Date: 2026-08-31

§2.2 Incremental Loading — adds snapshot_type VARCHAR to snapshot table.
  - "FULL"        : complete EDW scan; self-contained baseline.
  - "INCREMENTAL" : partial scan; ingestor back-fills unchanged objects
                    from the most recent FULL snapshot for the same
                    source_system.
  - NULL          : legacy rows (pre-Phase-2); treated as FULL by the ingestor.

Idempotent: skips the column add when it already exists (dev DBs created
via create_all during Phase-2 lab work already have it).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = '0418f861635f'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("snapshot")}

    if "snapshot_type" not in existing_cols:
        with op.batch_alter_table("snapshot", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("snapshot_type", sa.String(), nullable=True)
            )


def downgrade() -> None:
    with op.batch_alter_table("snapshot", schema=None) as batch_op:
        batch_op.drop_column("snapshot_type")
