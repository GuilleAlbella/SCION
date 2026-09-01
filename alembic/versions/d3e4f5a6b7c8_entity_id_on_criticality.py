"""entity_id FK column on object_criticality

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-01

§2.9 Integration Model -- adds entity_id (nullable INT) to object_criticality
so the entity history endpoint can join by stable ID instead of object_name
string, and the entity resolver can back-fill the FK on each ingest run.

The column is nullable to preserve backwards compatibility with existing rows
(pre-§2.9 data dictionaries will have NULL until the next ingest run or a
manual backfill via tools/backfill_entities.py).

Idempotent: skips the column and index if they already exist.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    existing_cols = {c["name"] for c in inspector.get_columns("object_criticality")}
    if "entity_id" not in existing_cols:
        with op.batch_alter_table("object_criticality") as batch_op:
            batch_op.add_column(
                sa.Column("entity_id", sa.Integer(), nullable=True)
            )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("object_criticality")}
    if "ix_object_criticality_entity" not in existing_indexes:
        op.create_index(
            "ix_object_criticality_entity",
            "object_criticality",
            ["entity_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_object_criticality_entity", table_name="object_criticality")
    with op.batch_alter_table("object_criticality") as batch_op:
        batch_op.drop_column("entity_id")
