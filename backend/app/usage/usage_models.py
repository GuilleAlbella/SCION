"""ORM models for Usage & Criticality Engine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UsageEvent(Base):
    """Records usage statistics for a database object.

    Populated from external JSON (parser output) via the ingestion endpoint.
    """

    __tablename__ = "usage_event"

    usage_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Nullable: rows persisted before v1.21.54 predate this column and have
    # no snapshot to backfill against automatically (see migration for the
    # one-time backfill of rows that CAN be inferred from ingest batching).
    # New imports always populate this via persist_object_usage's
    # `snapshot_id` parameter, so the null case shrinks to zero over time.
    snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    # §2.9 Integration Model (v2.04.00): stable entity ID across snapshots.
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    object_name: Mapped[str] = mapped_column(String, nullable=False)
    object_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    schema_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    query_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # §2.10 — populated once the PDCR extractor provides per-user rows.
    # NULL until then; the org-hierarchy dashboards degrade gracefully.
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
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
    # §2.9 Integration Model: stable entity FK so history queries can join by
    # ID rather than object_name string. Nullable for backward compatibility;
    # back-filled by entity_resolver.resolve_entities() on each ingest run.
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ``(snapshot_id, combined_score)`` is the exact ordering used by the
    # /usage criticality scorecard, the TAISA "what's most critical here?"
    # context fetch, and the criticality CSV export. Indexing on the score
    # too lets SQLite serve the top-N queries by index scan instead of a
    # sort over the full snapshot. Created in alembic c94d0e6a7b23.
    __table_args__ = (
        Index(
            "ix_object_criticality_snapshot_score",
            "snapshot_id",
            "combined_score",
        ),
        Index("ix_object_criticality_entity", "entity_id"),
    )
