"""add dict subtables: index_snapshot, partitioning_snapshot, ddl_text_snapshot

Revision ID: b83c9d5e6f12
Revises: a72b8c4f9d31
Create Date: 2026-04-29 17:00:00.000000

The data-dictionary ingest pipeline (v1.12) parses 6 files but only
persists 3 of them (databases / tables / columns) into dedicated
tables. Indices, partitioning and DDL text were "seen but not
persisted" — counted in the response but discarded.

This migration adds three sibling tables so the rest of SCION can
actually use that data:

  - `index_snapshot`        — one row per (index, column) pair, mirroring
                              DBC.IndicesV. Multi-column indexes appear as
                              multiple rows with same `index_number` and
                              ascending `column_position`.
  - `partitioning_snapshot` — one row per partitioning constraint on a
                              table. Stores the verbatim ConstraintText so
                              we can show the user exactly what Teradata
                              has, not a parsed reinterpretation.
  - `ddl_text_snapshot`     — one row per (table_id) with the full
                              assembled DDL. We store the concatenated
                              text rather than per-fragment because every
                              consumer (DDL Generator, TAISA context,
                              future code-diff) wants the whole thing.

All three are scoped by `table_id` (FK to `table_snapshot`) so they
participate in the existing snapshot-deletion cascade. No FK to
`snapshot` directly — going through `table_snapshot.schema_id ->
schema_snapshot.snapshot_id` is the canonical path and avoids
duplicate-source-of-truth bugs.

Indexes:
  - `(table_id, index_number)` on index_snapshot — fast "show me all
    columns of index N" lookups.
  - `(table_id)` on partitioning_snapshot and ddl_text_snapshot —
    fast per-object retrieval.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic identifiers.
revision: str = "b83c9d5e6f12"
down_revision: Union[str, None] = "a72b8c4f9d31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ──── index_snapshot ────
    op.create_table(
        "index_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "table_id",
            sa.Integer(),
            sa.ForeignKey("table_snapshot.table_id"),
            nullable=False,
        ),
        sa.Column("index_name", sa.String(), nullable=True),
        sa.Column("index_number", sa.Integer(), nullable=True),
        # Single-letter Teradata code: P=primary, S=secondary, U=unique,
        # K=primary key, etc. We store the raw code; UI maps it to a
        # human-friendly label via a small lookup. Keeping the raw code
        # means future codes (e.g. new TD versions) work without a
        # migration.
        sa.Column("index_type", sa.String(), nullable=True),
        sa.Column("unique_flag", sa.String(), nullable=True),  # 'Y' / 'N'
        sa.Column("column_name", sa.String(), nullable=False),
        sa.Column("column_position", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_index_snapshot_table_index",
        "index_snapshot",
        ["table_id", "index_number"],
        unique=False,
    )

    # ──── partitioning_snapshot ────
    op.create_table(
        "partitioning_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "table_id",
            sa.Integer(),
            sa.ForeignKey("table_snapshot.table_id"),
            nullable=False,
        ),
        # ConstraintType: P (primary partition), Q (sub-partition), etc.
        sa.Column("constraint_type", sa.String(), nullable=True),
        # ConstraintText: the actual partition expression, e.g.
        # `RANGE_N(order_date BETWEEN DATE '2020-01-01' ...)`. Can be
        # multi-line / multi-KB; sa.Text not String to avoid SQLite's
        # implicit truncation behaviour.
        sa.Column("constraint_text", sa.Text(), nullable=True),
        sa.Column("create_timestamp", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_partitioning_snapshot_table",
        "partitioning_snapshot",
        ["table_id"],
        unique=False,
    )

    # ──── ddl_text_snapshot ────
    op.create_table(
        "ddl_text_snapshot",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "table_id",
            sa.Integer(),
            sa.ForeignKey("table_snapshot.table_id"),
            # Unique because we always store the full assembled DDL,
            # not per-fragment. If a table already has a row, we
            # overwrite (handled in persister).
            nullable=False,
            unique=True,
        ),
        # The full CREATE statement as Teradata reported it. Can be
        # tens of KB for views with long bodies; sa.Text is correct
        # (no length cap).
        sa.Column("ddl_text", sa.Text(), nullable=False),
        # `request_text_fragments` — how many DBC.TableTextV rows we
        # concatenated. Useful for diagnostics: a fragment count of 1
        # on a 50KB DDL means TableTextV had a single big row;
        # fragment count of 50 means it was chunked. Either is valid
        # but the count helps us reason about edge cases later.
        sa.Column("request_text_fragments", sa.Integer(), nullable=False, default=1),
    )


def downgrade() -> None:
    op.drop_table("ddl_text_snapshot")
    op.drop_index("ix_partitioning_snapshot_table", table_name="partitioning_snapshot")
    op.drop_table("partitioning_snapshot")
    op.drop_index("ix_index_snapshot_table_index", table_name="index_snapshot")
    op.drop_table("index_snapshot")
