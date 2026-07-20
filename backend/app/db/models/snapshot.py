"""SQLAlchemy model for metadata snapshots representing full EDW states."""

from __future__ import annotations

from datetime import datetime
from typing import List

from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, JSON, String
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
    # Populated by the dict-import pipeline (v1.12+); NULL for parser-import
    # and demo-seed snapshots which don't have a per-run identifier.
    # Indexed (see migration a72b8c4f9d31) for fast idempotency lookups.
    extract_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    # §2.16 Staging Layer (v2.03.00): tracks import lifecycle.
    # pending → staged → committed | failed
    # Existing rows (pre-staging) default to 'committed' via migration server_default.
    import_status: Mapped[str] = mapped_column(String(20), nullable=False, default="committed")
    # Validation pass result: list of {type, severity, message, object_name?} dicts.
    # NULL = not yet validated or zero issues.
    validation_warnings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    schemas: Mapped[List["SchemaSnapshot"]] = relationship(
        back_populates="snapshot",
    )
