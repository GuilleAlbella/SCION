"""SQLAlchemy model for index metadata captured by the dict ingest."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IndexSnapshot(Base):
    """One row per (index, column) pair on a table.

    Multi-column indexes appear as multiple rows with the same
    `index_number` and `column_position` ascending — that's how
    `DBC.IndicesV` represents them, and we mirror it 1:1 to keep
    the mapping with Rahul's `.dat` extract dead obvious.

    Lifecycle: created/replaced by `dict_persister.persist_indices()`
    on every dict-import for a given snapshot. Cascades on delete
    via the `table_snapshot` FK.
    """

    __tablename__ = "index_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("table_snapshot.table_id"),
        nullable=False,
    )
    index_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    index_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Teradata index_type code: P (primary), S (secondary), U (unique),
    # K (primary key), etc. UI maps to human label.
    index_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    unique_flag: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    column_name: Mapped[str] = mapped_column(String, nullable=False)
    column_position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # The Indices viewer groups by ``(table_id, index_number)`` to assemble
    # multi-column indexes. Without this composite index the page does a
    # full scan of every row in the table, which on a 337k-index extract
    # was visibly sluggish. Created in alembic b83c9d5e6f12.
    __table_args__ = (
        Index("ix_index_snapshot_table_index", "table_id", "index_number"),
    )
