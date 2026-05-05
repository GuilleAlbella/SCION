"""add change_impact_summary table

Revision ID: f27c3d4e5f6b
Revises: e16b2c3d4f5a
Create Date: 2026-05-05 19:00:00.000000

The post-ingest pipeline now pre-aggregates per-change impact counts
into this table so ``POST /impact/batch`` doesn't need to run hundreds
of thousands of recursive-CTE walks on every request. See
``backend/app/graph/impact_models.py:ChangeImpactSummary`` for the
full rationale.

Idempotent: skip when the table already exists (a previous run that
got interrupted, or a fresh DB created via ``Base.metadata.create_all``
that already has it from the ORM definitions).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f27c3d4e5f6b"
down_revision: Union[str, None] = "e16b2c3d4f5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "change_impact_summary" in inspector.get_table_names():
        return

    op.create_table(
        "change_impact_summary",
        sa.Column("change_id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("direct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indirect_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("impact_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("max_depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["change_id"], ["change_event.change_id"]),
    )
    op.create_index(
        "ix_change_impact_summary_snapshot",
        "change_impact_summary",
        ["snapshot_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "change_impact_summary" not in inspector.get_table_names():
        return
    op.drop_index("ix_change_impact_summary_snapshot", table_name="change_impact_summary")
    op.drop_table("change_impact_summary")
