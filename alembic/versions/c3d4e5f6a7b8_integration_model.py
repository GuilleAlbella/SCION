"""integration model: object_entity table + entity_id FK columns

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-20

§2.9 Integration Model — persistent cross-snapshot entity identity.

Adds:
  - object_entity       stable entity table (one row per unique object ever seen)
  - table_snapshot.entity_id     nullable FK → object_entity
  - graph_node.entity_id         nullable FK → object_entity
  - usage_event.entity_id        nullable FK → object_entity
  - change_event.entity_id       nullable FK → object_entity

FK columns are nullable so existing rows are unaffected. The backfill
script (backend/tools/backfill_entities.py) populates entity_id for
all pre-existing snapshots after running this migration.

Design notes:
  - Resolution key is (entity_type, object_name) where object_name is the
    fully-qualified "SCHEMA.TABLE" string. node_uid is intentionally NOT
    used as a key — its format is inconsistent between SnapshotEngine and
    graph_builder.
  - first_seen_snapshot_id / last_seen_snapshot_id track the object's
    lifecycle across snapshots for the entity history API.
  - is_active flips to False when an object disappears from a snapshot.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"
    insp = sa_inspect(conn)
    existing_tables = insp.get_table_names()

    # ── object_entity ───────────────────────────────────────────────
    # Guard: idempotent in case a previous partial migration run created
    # the table before crashing on the ALTER TABLE steps.
    if "object_entity" not in existing_tables:
        op.create_table(
            "object_entity",
            sa.Column("entity_id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("entity_type", sa.String(20), nullable=False),
            sa.Column("schema_name", sa.String, nullable=False),
            sa.Column("object_name", sa.String, nullable=False),
            sa.Column(
                "first_seen_snapshot_id",
                sa.Integer,
                sa.ForeignKey("snapshot.snapshot_id"),
                nullable=False,
            ),
            sa.Column(
                "last_seen_snapshot_id",
                sa.Integer,
                sa.ForeignKey("snapshot.snapshot_id"),
                nullable=False,
            ),
            # server_default uses SQL-standard literals compatible with both
            # PostgreSQL and SQLite (true/now() are Postgres-only).
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        # Unique natural key — one entity row per (type, fully-qualified name)
        op.create_index(
            "uix_object_entity_type_name",
            "object_entity",
            ["entity_type", "object_name"],
            unique=True,
        )
        op.create_index("ix_object_entity_schema", "object_entity", ["schema_name"])
        op.create_index("ix_object_entity_active", "object_entity", ["is_active", "entity_type"])

    # ── entity_id FK on existing tables (nullable) ──────────────────
    # SQLite does not support ADD COLUMN with inline FK constraints and
    # does not enforce FK constraints, so we omit the FK on SQLite.
    # Each table is guarded so re-runs after partial failures are safe.
    _entity_tables = [
        ("table_snapshot", "ix_table_snapshot_entity"),
        ("graph_node",     "ix_graph_node_entity"),
        ("usage_event",    "ix_usage_event_entity"),
        ("change_event",   "ix_change_event_entity"),
    ]
    for tname, iname in _entity_tables:
        existing_cols = [c["name"] for c in insp.get_columns(tname)]
        if "entity_id" in existing_cols:
            continue  # already added in a prior partial run
        if is_sqlite:
            with op.batch_alter_table(tname) as batch_op:
                batch_op.add_column(sa.Column("entity_id", sa.Integer, nullable=True))
        else:
            op.add_column(
                tname,
                sa.Column(
                    "entity_id",
                    sa.Integer,
                    sa.ForeignKey("object_entity.entity_id"),
                    nullable=True,
                ),
            )
        op.create_index(iname, tname, ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_change_event_entity", table_name="change_event")
    with op.batch_alter_table("change_event") as batch_op:
        batch_op.drop_column("entity_id")

    op.drop_index("ix_usage_event_entity", table_name="usage_event")
    with op.batch_alter_table("usage_event") as batch_op:
        batch_op.drop_column("entity_id")

    op.drop_index("ix_graph_node_entity", table_name="graph_node")
    with op.batch_alter_table("graph_node") as batch_op:
        batch_op.drop_column("entity_id")

    op.drop_index("ix_table_snapshot_entity", table_name="table_snapshot")
    with op.batch_alter_table("table_snapshot") as batch_op:
        batch_op.drop_column("entity_id")

    op.drop_index("ix_object_entity_active", table_name="object_entity")
    op.drop_index("ix_object_entity_schema", table_name="object_entity")
    op.drop_index("uix_object_entity_type_name", table_name="object_entity")
    op.drop_table("object_entity")
