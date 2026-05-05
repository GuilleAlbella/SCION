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
    # Indexed: the DiffEngine's per-snapshot loaders filter by snapshot_id on
    # every diff. SQLite does NOT auto-index FK columns, so without this hint
    # a snapshot with 10k schemas forces a full scan of the table for every
    # diff pair. See alembic d05a1b2c3d4e for the migration that backfills
    # this on existing DBs.
    snapshot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("snapshot.snapshot_id"),
        nullable=False,
        index=True,
    )
    schema_name: Mapped[str] = mapped_column(String, nullable=False)

    snapshot: Mapped["Snapshot"] = relationship(
        back_populates="schemas",
    )
    tables: Mapped[List["TableSnapshot"]] = relationship(
        back_populates="schema",
    )
