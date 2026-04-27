"""SQLAlchemy model for metadata snapshots representing full EDW states."""

from __future__ import annotations

from datetime import datetime
from typing import List

from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Snapshot(Base):
    """Represents a full EDW state at a specific point in time."""

    __tablename__ = "snapshot"

    snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_system: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    structural_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    object_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    schemas: Mapped[List["SchemaSnapshot"]] = relationship(
        back_populates="snapshot",
    )
