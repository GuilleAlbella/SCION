"""ORM models for the §2.16 Staging Layer.

staging_table_import  — one row per table/view captured at ingest,
                        before promotion to table_snapshot.
staging_column_import — one row per column, linked to staging_table_import.

Both tables support per-row validation status so individual objects can be
accepted, rejected, or resolved (DDL timestamp winner) independently.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class StagingTableImport(Base):
    __tablename__ = "staging_table_import"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("snapshot.snapshot_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_name: Mapped[str] = mapped_column(String, nullable=False)
    table_name: Mapped[str] = mapped_column(String, nullable=False)
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    # pending | accepted | rejected | resolved
    row_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    validation_errors: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"),
    )

    columns: Mapped[list["StagingColumnImport"]] = relationship(
        back_populates="staging_table",
        cascade="all, delete-orphan",
    )


class StagingColumnImport(Base):
    __tablename__ = "staging_column_import"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    staging_table_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("staging_table_import.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("snapshot.snapshot_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    column_name: Mapped[str] = mapped_column(String, nullable=False)
    data_type: Mapped[str] = mapped_column(String, nullable=False)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    row_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    validation_errors: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"),
    )

    staging_table: Mapped["StagingTableImport"] = relationship(back_populates="columns")
