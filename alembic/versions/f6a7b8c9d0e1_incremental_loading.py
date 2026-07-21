"""incremental_loading — §2.2 baseline tracking + gap detection.

Adds three columns to snapshot:
  - baseline_snapshot_id: FK to the baseline this snapshot was compared against
    (NULL for baselines themselves)
  - cumulative_object_count: distinct objects seen across all snapshots from
    day-zero baseline through this one
  - gap_detected: True when this snapshot triggered a new baseline because the
    gap since the last extract exceeded the configured threshold (default 7 days)

Revision: f6a7b8c9d0e1
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "snapshot",
        sa.Column("baseline_snapshot_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "snapshot",
        sa.Column("cumulative_object_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "snapshot",
        sa.Column(
            "gap_detected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_snapshot_baseline_snapshot_id",
        "snapshot",
        ["baseline_snapshot_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_snapshot_baseline_snapshot_id", table_name="snapshot")
    op.drop_column("snapshot", "gap_detected")
    op.drop_column("snapshot", "cumulative_object_count")
    op.drop_column("snapshot", "baseline_snapshot_id")
