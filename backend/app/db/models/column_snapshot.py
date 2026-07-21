"""SQLAlchemy model for technical column metadata within a table snapshot."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ColumnSnapshot(Base):
    """Represents technical column metadata within a table snapshot."""

    __tablename__ = "column_snapshot"

    column_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Indexed: with 9.8M columns on a Transcend extract, every JOIN that
    # walks columns by table_id (DiffEngine, graph builder, schema-tree
    # endpoint) becomes an O(N) scan without this. The single biggest
    # perf win on the snapshot tables. See alembic d05a1b2c3d4e.
    table_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("table_snapshot.table_id"),
        nullable=False,
        index=True,
    )
    column_name: Mapped[str] = mapped_column(String, nullable=False)
    data_type: Mapped[str] = mapped_column(String, nullable=False)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)

    # §2.12 AI Column Classification — TAISA PII labels cached here so
    # GET /columns/pii is a plain DB read. NULL = not yet classified.
    pii_label: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pii_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pii_classified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    table: Mapped["TableSnapshot"] = relationship(
        back_populates="columns",
    )
