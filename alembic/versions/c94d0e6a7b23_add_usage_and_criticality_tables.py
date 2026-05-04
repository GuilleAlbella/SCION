"""add usage_event and object_criticality tables

Revision ID: c94d0e6a7b23
Revises: b83c9d5e6f12
Create Date: 2026-05-04 18:30:00.000000

Backfills the two tables that the Usage & Criticality engine has
relied on since v1.07 but that were never given an Alembic migration.

The models live in `app.usage.usage_models` and are registered in
`app.db.base`, so until now the only path to a working DB was to
run `tools/bootstrap_sqlite_db.py` (which calls
`Base.metadata.create_all`). That works locally but breaks any
container/CI flow that relies on `alembic upgrade head` from an
empty DB — Helton ran into this while setting up his environment.

After this migration, a fresh `alembic upgrade head` produces a
fully functional schema with no extra steps. The bootstrap script
remains as a convenience for demo wipes but is no longer the
canonical creation path.

Schema mirrors `app/usage/usage_models.py` exactly. No FKs declared
to `snapshot.snapshot_id` because the existing model doesn't
declare them either — we keep the migration faithful to the ORM
rather than introducing new constraints in a backfill.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Alembic identifiers.
revision: str = "c94d0e6a7b23"
down_revision: Union[str, None] = "b83c9d5e6f12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ──── usage_event ────
    # Populated from external JSON (parser output) via the usage
    # ingestion endpoint. One row per (object, source) reading.
    op.create_table(
        "usage_event",
        sa.Column("usage_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("object_name", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=True),
        sa.Column("schema_name", sa.String(), nullable=True),
        sa.Column("query_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("user_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        # JSON column — SQLite stores as TEXT, Postgres as JSONB. The
        # ORM uses sa.JSON which lets the driver pick the right type.
        sa.Column("source_json", sa.JSON(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )

    # ──── object_criticality ────
    # Computed by `criticality_engine.compute_criticality(snapshot_id)`
    # as part of the post-ingest pipeline. One row per (object,
    # snapshot) — the engine deletes & re-inserts for a snapshot on
    # recompute, so we don't add a unique constraint that would
    # fight that pattern.
    op.create_table(
        "object_criticality",
        sa.Column("criticality_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("object_name", sa.String(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("usage_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("graph_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("combined_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "criticality_level",
            sa.String(),
            nullable=False,
            server_default="LOW",
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    # Most queries (TAISA context, export, criticality engine) filter
    # by snapshot_id and order by combined_score — composite index
    # serves both shapes.
    op.create_index(
        "ix_object_criticality_snapshot_score",
        "object_criticality",
        ["snapshot_id", "combined_score"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_object_criticality_snapshot_score",
        table_name="object_criticality",
    )
    op.drop_table("object_criticality")
    op.drop_table("usage_event")
