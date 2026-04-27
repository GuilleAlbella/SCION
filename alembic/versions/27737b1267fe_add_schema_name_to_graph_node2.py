"""add node_uid to graph_node

Revision ID: 27737b1267fe
Revises: df5f450f20b3
Create Date: 2026-02-09 08:14:12.730946
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "27737b1267fe"
down_revision: Union[str, None] = "df5f450f20b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "graph_node",
        sa.Column("node_uid", sa.String(), nullable=False, server_default=""),
    )
    # IMPORTANTE: no hacemos alter_column aquí para evitar el
    #   ALTER TABLE ... DROP DEFAULT
    # que rompe en SQLite.


def downgrade() -> None:
    op.drop_column("graph_node", "node_uid")