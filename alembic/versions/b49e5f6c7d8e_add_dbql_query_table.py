"""add dbql_query table

Revision ID: b49e5f6c7d8e
Revises: a38d4e5f6c7d
Create Date: 2026-05-28 16:00:00.000000

Pipeline 3 (PR-C of 6) adds ingest of Rahul's PDCR usage extracts.
The `pdcr_log_*.dat` files arrive as fragments — one row per
(QueryID, SqlRowNo) — and the reader reassembles them into full
SQL statements. This migration creates the destination table for
those reassembled queries.

Idempotent: the table is created only when it doesn't already
exist, matching the convention every other Pipeline-3-adjacent
migration uses (a38d4e5f6c7d, f27c3d4e5f6b, etc).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b49e5f6c7d8e"
down_revision: Union[str, None] = "a38d4e5f6c7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dbql_query" in inspector.get_table_names():
        return

    op.create_table(
        "dbql_query",
        sa.Column(
            "dbql_query_id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("query_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "collect_timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("proc_id", sa.Integer(), nullable=True),
        sa.Column("sql_text", sa.Text(), nullable=False),
        sa.Column("default_database", sa.String(), nullable=True),
        sa.Column("qb_job_name", sa.String(), nullable=True),
        sa.Column("qb_proc_name", sa.String(), nullable=True),
        sa.Column("platform_name", sa.String(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "query_id",
            "collect_timestamp",
            name="uq_dbql_query_id_collect_ts",
        ),
    )

    # Three indexes chosen for the access patterns the DBQL store
    # serves. Created here (not via composite UniqueConstraint) so the
    # planner can use them independently:
    #
    #   - DataDNA correlation lookup: `WHERE query_id = ?`
    #     ix_dbql_query_id is the primary lookup path.
    #
    #   - Operator queries: "what ran on 2026-05-12?" — log_date index
    #     covers single-day windows; date-range queries also use it.
    #
    #   - "Usage by default_database, by day" rollups — composite
    #     (default_database, log_date) is the standard shape for the
    #     intelligence engine's per-database query-count panel.
    op.create_index("ix_dbql_query_id", "dbql_query", ["query_id"])
    op.create_index("ix_dbql_query_log_date", "dbql_query", ["log_date"])
    op.create_index(
        "ix_dbql_query_db_date",
        "dbql_query",
        ["default_database", "log_date"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "dbql_query" not in inspector.get_table_names():
        return
    op.drop_index("ix_dbql_query_db_date", table_name="dbql_query")
    op.drop_index("ix_dbql_query_log_date", table_name="dbql_query")
    op.drop_index("ix_dbql_query_id", table_name="dbql_query")
    op.drop_table("dbql_query")
