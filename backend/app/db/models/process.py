"""SQLAlchemy model for a process (SQL script / job) captured from the parser.

A "process" represents a unit of work in the source warehouse — typically a
SQL script, ETL job, or stored procedure run. Each process belongs to a
`processGroup` (e.g. "dbql" for queries coming from DBQL logs) and contains
one or more `steps` (statements / query blocks).

Introduced in SCION v1.04 as part of the DataDNA parser integration.
The parser's `processes` array maps 1:1 to rows in this table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Process(Base):
    """A process (SQL script / job / stored-procedure run) from the parser feed.

    Attributes:
        process_id: Internal surrogate key.
        snapshot_id: Which SCION snapshot this process belongs to (parser runs
            are ingested as snapshots, so every process ties back to a run).
        process_natural_key: Stable identifier from the parser, e.g.
            ``"dbql_DBQL_insert_sample"``. Unique within a snapshot.
        process_type: Classification from the parser (``SQL_Script``,
            ``Stored_Procedure``, ``ETL_Job``, etc.).
        process_group_natural_key: Upstream grouping label, e.g. ``"dbql"``.
        platform_natural_key: Source platform (``"TERADATA"``, etc.) for
            multi-platform lineage.
        parse_run_id: Correlates back to the parser run that produced this row.
        parse_timestamp: When the parser extracted this process.
        created_at: When SCION ingested it.
    """

    __tablename__ = "process"

    process_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshot.snapshot_id"), nullable=False
    )
    process_natural_key: Mapped[str] = mapped_column(String, nullable=False)
    process_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    process_group_natural_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    platform_natural_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    parse_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    parse_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # Back-ref: a process has many steps. Declared via string to avoid circular
    # import at module load time (step.py imports Process too).
    steps: Mapped[List["Step"]] = relationship(back_populates="process")
