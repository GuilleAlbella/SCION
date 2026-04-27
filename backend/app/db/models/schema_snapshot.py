"""SQLAlchemy model for logical schemas within a metadata snapshot."""

from __future__ import annotations

from typing import List

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SchemaSnapshot(Base):
    """Represents a logical schema captured within a snapshot."""

    __tablename__ = "schema_snapshot"

    schema_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("snapshot.snapshot_id"),
        nullable=False,
    )
    schema_name: Mapped[str] = mapped_column(String, nullable=False)

    snapshot: Mapped["Snapshot"] = relationship(
        back_populates="schemas",
    )
    tables: Mapped[List["TableSnapshot"]] = relationship(
        back_populates="schema",
    )
