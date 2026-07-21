"""reference data tables: user/team/dept/app hierarchy + username on usage_event

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-20

§2.10 Reference Data Support — three new hierarchies:
  1. Org chart:    department_entity → team_entity → user_entity
  2. Business apps: application_entity + database_application_mapping
                                       + table_application_mapping
  3. usage_event.username — nullable column for when the PDCR extractor
     upgrades to per-user rows (currently only user_count is available).
"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Org hierarchy ────────────────────────────────────────────────

    op.create_table(
        "department_entity",
        sa.Column("department_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("department_name", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("department_name", name="uq_department_name"),
    )

    op.create_table(
        "team_entity",
        sa.Column("team_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("team_name", sa.Text, nullable=False),
        sa.Column("department_id", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["department_id"], ["department_entity.department_id"]),
        sa.UniqueConstraint("team_name", name="uq_team_name"),
    )
    op.create_index("ix_team_entity_department_id", "team_entity", ["department_id"])

    op.create_table(
        "user_entity",
        sa.Column("user_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text, nullable=True),
        sa.Column("email", sa.Text, nullable=True),
        sa.Column("team_id", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["team_id"], ["team_entity.team_id"]),
        sa.UniqueConstraint("username", name="uq_user_username"),
    )
    op.create_index("ix_user_entity_team_id", "user_entity", ["team_id"])

    # ── Business applications ─────────────────────────────────────────

    op.create_table(
        "application_entity",
        sa.Column("application_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("application_name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("owner_team_id", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["owner_team_id"], ["team_entity.team_id"]),
        sa.UniqueConstraint("application_name", name="uq_application_name"),
    )
    op.create_index("ix_application_entity_owner_team_id", "application_entity", ["owner_team_id"])

    op.create_table(
        "database_application_mapping",
        sa.Column("mapping_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("schema_name", sa.String, nullable=False),
        sa.Column("application_id", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["application_entity.application_id"]
        ),
        sa.UniqueConstraint("schema_name", "application_id", name="uq_db_app"),
    )
    op.create_index(
        "ix_database_application_mapping_schema",
        "database_application_mapping",
        ["schema_name"],
    )

    op.create_table(
        "table_application_mapping",
        sa.Column("mapping_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("schema_name", sa.String, nullable=False),
        sa.Column("table_name", sa.String, nullable=False),
        sa.Column("application_id", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["application_entity.application_id"]
        ),
        sa.UniqueConstraint("schema_name", "table_name", "application_id", name="uq_table_app"),
    )
    op.create_index(
        "ix_table_application_mapping_schema_table",
        "table_application_mapping",
        ["schema_name", "table_name"],
    )

    # ── usage_event.username — future per-user PDCR rows ─────────────
    op.add_column("usage_event", sa.Column("username", sa.Text, nullable=True))
    op.create_index("ix_usage_event_username", "usage_event", ["username"])


def downgrade() -> None:
    op.drop_index("ix_usage_event_username", table_name="usage_event")
    op.drop_column("usage_event", "username")

    op.drop_index(
        "ix_table_application_mapping_schema_table", table_name="table_application_mapping"
    )
    op.drop_table("table_application_mapping")

    op.drop_index(
        "ix_database_application_mapping_schema", table_name="database_application_mapping"
    )
    op.drop_table("database_application_mapping")

    op.drop_index("ix_application_entity_owner_team_id", table_name="application_entity")
    op.drop_table("application_entity")

    op.drop_index("ix_user_entity_team_id", table_name="user_entity")
    op.drop_table("user_entity")

    op.drop_index("ix_team_entity_department_id", table_name="team_entity")
    op.drop_table("team_entity")

    op.drop_table("department_entity")
