"""add ddl_alter_timestamp to table_snapshot

Revision ID: b3f2e1d0c9a8
Revises: 0418f861635f
Create Date: 2026-08-31

§2.4 DDL Timestamp Merge — stores the last-alter time from DBC.TablesV on each
table_snapshot row so the diff engine can distinguish a DDL change from a
re-capture by a different extraction source (DBQL vs dict).

Applies to: views, stored procedures, macros, triggers — any object type whose
DDL is managed through the data dictionary.

Idempotent: skips the column add when it already exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = 'b3f2e1d0c9a8'
down_revision: Union[str, None] = '0418f861635f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("table_snapshot")}

    if "ddl_alter_timestamp" not in existing_cols:
        with op.batch_alter_table("table_snapshot", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("ddl_alter_timestamp", sa.DateTime(), nullable=True)
            )


def downgrade() -> None:
    with op.batch_alter_table("table_snapshot", schema=None) as batch_op:
        batch_op.drop_column("ddl_alter_timestamp")
