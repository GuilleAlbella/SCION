"""staging layer: import_status on snapshot + staging tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-20

Adds:
  - snapshot.import_status  VARCHAR(20) NOT NULL default 'committed'
    Tracks where a snapshot is in the Staging → Integration pipeline.
    Values: pending | staged | committed | failed
    Existing rows default to 'committed' (they predate staging).

  - snapshot.validation_warnings  JSON nullable
    Stores the result of the §2.16.b validation pass as a list of
    warning/error dicts: [{type, message, object_name?, severity}].
    NULL means not yet validated or no issues found.

  - staging_table_import
    Raw table rows captured at ingest time before promotion to
    table_snapshot / schema_snapshot.  Row-level status tracks
    whether each object passed validation.

  - staging_column_import
    Raw column rows, one per (staging_table_import, column).
"""

from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── snapshot additions ──────────────────────────────────────────
    op.add_column(
        "snapshot",
        sa.Column(
            "import_status",
            sa.String(20),
            nullable=False,
            server_default="committed",
        ),
    )
    op.add_column(
        "snapshot",
        sa.Column("validation_warnings", sa.JSON, nullable=True),
    )

    # ── staging_table_import ────────────────────────────────────────
    op.create_table(
        "staging_table_import",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "snapshot_id",
            sa.Integer,
            sa.ForeignKey("snapshot.snapshot_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("schema_name", sa.String, nullable=False),
        sa.Column("table_name", sa.String, nullable=False),
        sa.Column("object_type", sa.String, nullable=False),
        # pending | accepted | rejected | resolved
        sa.Column("row_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("validation_errors", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_staging_table_import_snapshot",
        "staging_table_import",
        ["snapshot_id"],
    )
    op.create_index(
        "ix_staging_table_import_snapshot_name",
        "staging_table_import",
        ["snapshot_id", "schema_name", "table_name"],
    )

    # ── staging_column_import ───────────────────────────────────────
    op.create_table(
        "staging_column_import",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "staging_table_id",
            sa.Integer,
            sa.ForeignKey("staging_table_import.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            sa.Integer,
            sa.ForeignKey("snapshot.snapshot_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("column_name", sa.String, nullable=False),
        sa.Column("data_type", sa.String, nullable=False),
        sa.Column("nullable", sa.Boolean, nullable=False),
        sa.Column("ordinal_position", sa.Integer, nullable=False),
        sa.Column("row_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("validation_errors", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_staging_column_import_table",
        "staging_column_import",
        ["staging_table_id"],
    )
    op.create_index(
        "ix_staging_column_import_snapshot",
        "staging_column_import",
        ["snapshot_id"],
    )


def downgrade() -> None:
    op.drop_table("staging_column_import")
    op.drop_table("staging_table_import")
    op.drop_column("snapshot", "validation_warnings")
    op.drop_column("snapshot", "import_status")
