"""add parser integration tables (process, step, attribute_lineage)

Revision ID: f1a8b3c5d207
Revises: ea1f255a8cd9
Create Date: 2026-04-20 16:00:00.000000

Adds the three tables needed for SCION v1.04 parser integration:
- `process`          : SQL scripts / jobs captured by the DataDNA parser
- `step`             : statements / query blocks inside a process
- `attribute_lineage`: column-to-column lineage (Tier 1 / Tier 2)

These coexist with the existing snapshot / schema_snapshot / graph_*
tables. No existing tables are modified.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1a8b3c5d207"
down_revision: Union[str, None] = "ea1f255a8cd9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ──── process: one row per SQL script / job ────
    op.create_table(
        "process",
        sa.Column("process_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_id", sa.Integer(),
                  sa.ForeignKey("snapshot.snapshot_id"), nullable=False),
        sa.Column("process_natural_key", sa.String(), nullable=False),
        sa.Column("process_type", sa.String(), nullable=True),
        sa.Column("process_group_natural_key", sa.String(), nullable=True),
        sa.Column("platform_natural_key", sa.String(), nullable=True),
        sa.Column("parse_run_id", sa.String(), nullable=True),
        sa.Column("parse_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.current_timestamp()),
    )
    # Fast lookup by (snapshot, natural_key) for dedup checks and joins.
    op.create_index(
        "ix_process_snapshot_natural",
        "process",
        ["snapshot_id", "process_natural_key"],
    )

    # ──── step: one row per statement / query block inside a process ────
    op.create_table(
        "step",
        sa.Column("step_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_id", sa.Integer(),
                  sa.ForeignKey("snapshot.snapshot_id"), nullable=False),
        sa.Column("step_natural_key", sa.String(), nullable=False),
        sa.Column("process_id", sa.Integer(),
                  sa.ForeignKey("process.process_id"), nullable=False),
        sa.Column("parent_step_natural_key", sa.String(), nullable=True),
        sa.Column("step_level", sa.String(), nullable=True),
        sa.Column("step_type", sa.String(), nullable=True),
        sa.Column("platform_natural_key", sa.String(), nullable=True),
        sa.Column("parse_run_id", sa.String(), nullable=True),
        sa.Column("parse_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index(
        "ix_step_snapshot_natural",
        "step",
        ["snapshot_id", "step_natural_key"],
    )
    op.create_index(
        "ix_step_process",
        "step",
        ["process_id"],
    )

    # ──── attribute_lineage: column-to-column lineage from Tier 1 / Tier 2 ────
    op.create_table(
        "attribute_lineage",
        sa.Column("lineage_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_id", sa.Integer(),
                  sa.ForeignKey("snapshot.snapshot_id"), nullable=False),
        sa.Column("source_attribute_natural_key", sa.String(), nullable=False),
        sa.Column("source_dataset_natural_key", sa.String(), nullable=True),
        sa.Column("target_attribute_natural_key", sa.String(), nullable=False),
        sa.Column("target_dataset_natural_key", sa.String(), nullable=True),
        sa.Column("step_natural_key", sa.String(), nullable=True),
        sa.Column("tier", sa.String(), nullable=True),
        # Text because expressions can be multi-kilobyte long-IN clauses.
        sa.Column("expression", sa.Text(), nullable=True),
        sa.Column("transformation_type", sa.String(), nullable=True),
        sa.Column("parse_run_id", sa.String(), nullable=True),
        sa.Column("parse_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.current_timestamp()),
    )
    # Two indexes because both endpoints are queried independently (source→
    # forwards lookups for "what downstream columns depend on X" vs
    # target→reverse lookups for "what populates X").
    op.create_index(
        "ix_attr_lineage_source",
        "attribute_lineage",
        ["snapshot_id", "source_attribute_natural_key"],
    )
    op.create_index(
        "ix_attr_lineage_target",
        "attribute_lineage",
        ["snapshot_id", "target_attribute_natural_key"],
    )


def downgrade() -> None:
    # Drop in reverse dependency order (step → process, then the standalone
    # attribute_lineage).
    op.drop_index("ix_attr_lineage_target", table_name="attribute_lineage")
    op.drop_index("ix_attr_lineage_source", table_name="attribute_lineage")
    op.drop_table("attribute_lineage")

    op.drop_index("ix_step_process", table_name="step")
    op.drop_index("ix_step_snapshot_natural", table_name="step")
    op.drop_table("step")

    op.drop_index("ix_process_snapshot_natural", table_name="process")
    op.drop_table("process")
