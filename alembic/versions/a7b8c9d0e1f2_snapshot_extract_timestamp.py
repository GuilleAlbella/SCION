"""snapshot_extract_timestamp — §2.13 Manifest-Derived Timestamps.

Adds extract_timestamp to snapshot: the UTC wall-clock time when the
Teradata extractor ran on the client side (parsed from extract_run_id
prefix by dict_persister). NULL for parser-import and demo snapshots
that have no extract_run_id.

Revision: a7b8c9d0e1f2
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "snapshot",
        sa.Column("extract_timestamp", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("snapshot", "extract_timestamp")
