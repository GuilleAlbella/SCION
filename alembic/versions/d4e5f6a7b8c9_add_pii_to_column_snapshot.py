"""add pii classification columns to column_snapshot

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-20

§2.12 AI Column Classification — TAISA-generated PII labels cached directly
on column_snapshot so GET /columns/pii is a plain DB read and classification
only reruns when force=true.
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("column_snapshot", sa.Column("pii_label", sa.Text, nullable=True))
    op.add_column("column_snapshot", sa.Column("pii_confidence", sa.Float, nullable=True))
    op.add_column(
        "column_snapshot",
        sa.Column("pii_classified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("column_snapshot", "pii_classified_at")
    op.drop_column("column_snapshot", "pii_confidence")
    op.drop_column("column_snapshot", "pii_label")
