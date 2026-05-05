"""SQLAlchemy model for table partitioning metadata."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PartitioningSnapshot(Base):
    """One row per partitioning constraint on a table.

    Stores `ConstraintText` verbatim — Teradata's representation of
    the partition expression (e.g.
    `RANGE_N(order_date BETWEEN DATE '2020-01-01' ...)`). We don't
    parse it because:
      1. Customers want to see exactly what Teradata reported, not a
         lossy reinterpretation.
      2. The grammar is variable across TD versions; a parser here
         would be a maintenance tax with no current consumer.

    Cascades on delete via `table_snapshot` FK.
    """

    __tablename__ = "partitioning_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("table_snapshot.table_id"),
        nullable=False,
    )
    # Single-letter Teradata code (P primary, Q sub-partition, etc.).
    constraint_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Multi-line / multi-KB possible — Text not String to dodge any
    # implicit truncation.
    constraint_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    create_timestamp: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # ``table_id`` is how every consumer (the Partitioning panel, dict-import
    # joins, schema-tree assembly) reads this table. Created in alembic
    # b83c9d5e6f12 alongside the table itself.
    __table_args__ = (
        Index("ix_partitioning_snapshot_table", "table_id"),
    )
