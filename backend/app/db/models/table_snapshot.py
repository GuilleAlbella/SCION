"""SQLAlchemy model for tables or views within a schema snapshot."""

from __future__ import annotations

from typing import List

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TableSnapshot(Base):
    """Represents a table or view within a schema snapshot."""

    __tablename__ = "table_snapshot"

    table_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Indexed: every JOIN against schema_snapshot in DiffEngine.compute_diff
    # filters tables by schema_id. With 240k tables in a Transcend extract,
    # the un-indexed scan dominates diff time. See alembic d05a1b2c3d4e.
    schema_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("schema_snapshot.schema_id"),
        nullable=False,
        index=True,
    )
    table_name: Mapped[str] = mapped_column(String, nullable=False)
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    # §2.9 Integration Model (v2.04.00): stable entity ID across snapshots.
    # NULL for rows ingested before the entity resolution pass.
    entity_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("object_entity.entity_id"),
        nullable=True,
        index=True,
    )

    schema: Mapped["SchemaSnapshot"] = relationship(
        back_populates="tables",
    )
    columns: Mapped[List["ColumnSnapshot"]] = relationship(
        back_populates="table",
    )
