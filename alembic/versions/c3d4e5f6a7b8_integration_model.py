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

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── object_entity ───────────────────────────────────────────────
    op.create_table(
        "object_entity",
        sa.Column("entity_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(20), nullable=False),   # TABLE VIEW SCHEMA COLUMN
        sa.Column("schema_name", sa.String, nullable=False),
        sa.Column("object_name", sa.String, nullable=False),       # SCHEMA.TABLE
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
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Unique natural key — one entity row per (type, fully-qualified name)
    op.create_index(
        "uix_object_entity_type_name",
        "object_entity",
        ["entity_type", "object_name"],
        unique=True,
    )
    op.create_index(
        "ix_object_entity_schema",
        "object_entity",
        ["schema_name"],
    )
    op.create_index(
        "ix_object_entity_active",
        "object_entity",
        ["is_active", "entity_type"],
    )

    # ── entity_id FK on existing tables (nullable) ──────────────────
    op.add_column(
        "table_snapshot",
        sa.Column("entity_id", sa.Integer, sa.ForeignKey("object_entity.entity_id"), nullable=True),
    )
    op.create_index("ix_table_snapshot_entity", "table_snapshot", ["entity_id"])

    op.add_column(
        "graph_node",
        sa.Column("entity_id", sa.Integer, sa.ForeignKey("object_entity.entity_id"), nullable=True),
    )
    op.create_index("ix_graph_node_entity", "graph_node", ["entity_id"])

    op.add_column(
        "usage_event",
        sa.Column("entity_id", sa.Integer, sa.ForeignKey("object_entity.entity_id"), nullable=True),
    )
    op.create_index("ix_usage_event_entity", "usage_event", ["entity_id"])

    op.add_column(
        "change_event",
        sa.Column("entity_id", sa.Integer, sa.ForeignKey("object_entity.entity_id"), nullable=True),
    )
    op.create_index("ix_change_event_entity", "change_event", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_change_event_entity", table_name="change_event")
    op.drop_column("change_event", "entity_id")

    op.drop_index("ix_usage_event_entity", table_name="usage_event")
    op.drop_column("usage_event", "entity_id")

    op.drop_index("ix_graph_node_entity", table_name="graph_node")
    op.drop_column("graph_node", "entity_id")

    op.drop_index("ix_table_snapshot_entity", table_name="table_snapshot")
    op.drop_column("table_snapshot", "entity_id")

    op.drop_index("ix_object_entity_active", table_name="object_entity")
    op.drop_index("ix_object_entity_schema", table_name="object_entity")
    op.drop_index("uix_object_entity_type_name", table_name="object_entity")
    op.drop_table("object_entity")
