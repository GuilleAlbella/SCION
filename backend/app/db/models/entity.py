"""ORM model for §2.9 Integration Model — persistent cross-snapshot entity identity.

ObjectEntity: one row per unique metadata object ever ingested.
The entity persists across snapshots via the natural key (entity_type, object_name).
Resolution uses (entity_type, schema_name + '.' + object_name) — NOT node_uid,
whose format is inconsistent between SnapshotEngine and graph_builder.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ObjectEntity(Base):
    __tablename__ = "object_entity"

    entity_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # TABLE | VIEW | SCHEMA | COLUMN — matches object_type in TableSnapshot / GraphNode
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    schema_name: Mapped[str] = mapped_column(String, nullable=False)
    # Fully-qualified: "SCHEMA.TABLE"
    object_name: Mapped[str] = mapped_column(String, nullable=False)

    first_seen_snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshot.snapshot_id"), nullable=False
    )
    last_seen_snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshot.snapshot_id"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("uix_object_entity_type_name", "entity_type", "object_name", unique=True),
        Index("ix_object_entity_schema", "schema_name"),
        Index("ix_object_entity_active", "is_active", "entity_type"),
    )
