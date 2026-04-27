"""ORM models for Usage & Criticality Engine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UsageEvent(Base):
    """Records usage statistics for a database object.

    Populated from external JSON (parser output) via the ingestion endpoint.
    """

    __tablename__ = "usage_event"

    usage_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    object_name: Mapped[str] = mapped_column(String, nullable=False)
    object_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    schema_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    query_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_accessed: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ObjectCriticality(Base):
    """Computed criticality score for a database object.

    Combines usage frequency with graph impact metrics to produce
    a single criticality level.
    """

    __tablename__ = "object_criticality"

    criticality_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    object_name: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_id: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    graph_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    combined_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    criticality_level: Mapped[str] = mapped_column(String, nullable=False, default="LOW")
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
