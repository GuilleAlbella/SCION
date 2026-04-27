"""SQLAlchemy model for technical column metadata within a table snapshot."""

from __future__ import annotations

from typing import List

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ColumnSnapshot(Base):
    """Represents technical column metadata within a table snapshot."""

    __tablename__ = "column_snapshot"

    column_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("table_snapshot.table_id"),
        nullable=False,
    )
    column_name: Mapped[str] = mapped_column(String, nullable=False)
    data_type: Mapped[str] = mapped_column(String, nullable=False)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)

    table: Mapped["TableSnapshot"] = relationship(
        back_populates="columns",
    )
