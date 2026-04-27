"""add schema_name to graph_node

Revision ID: df5f450f20b3
Revises: 4d5e6f708192
Create Date: 2026-02-09 07:53:52.997050

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'df5f450f20b3'
down_revision: Union[str, None] = '4d5e6f708192'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column(
        "graph_node",
        sa.Column("schema_name", sa.String(), nullable=True),
    )
 
 
def downgrade():
    op.drop_column("graph_node", "schema_name")