"""SQLAlchemy model for a step inside a process (statement or query block).

A "step" is a sub-unit of a process — it can be a STATEMENT level (e.g. a
single INSERT, CREATE TABLE) or a QUERY_BLOCK level (a subquery / SELECT
within a statement). Steps can have a parent step for nesting.

This lets SCION answer questions like "which statement within this job
touches table X?" which is richer than the bare script→table lineage.

Introduced in SCION v1.04 alongside the parser integration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Step(Base):
    """A statement or query block inside a process.

    Attributes:
        step_id: Internal surrogate key.
        snapshot_id: Ties the step to a SCION snapshot (matches parent process).
        step_natural_key: Parser-stable ID, e.g. ``"dbql_DBQL_insert_sample|S1"``
            or ``"dbql_DBQL_insert_sample|S1_Q1"`` for nested query blocks.
        process_id: FK to the parent ``process`` row.
        parent_step_natural_key: When this step is a sub-step (query block
            inside a statement), references the enclosing step. ``None`` at
            the top (statement) level.
        step_level: ``"STATEMENT"`` or ``"QUERY_BLOCK"``.
        step_type: SQL operation (``"INSERT"``, ``"SELECT"``, ``"UPDATE"``,
            ``"CREATE_TABLE"``, etc.).
        platform_natural_key: Source platform.
        parse_run_id: Correlates with the parser run.
        parse_timestamp: When the parser extracted this step.
        created_at: When SCION ingested it.
    """

    __tablename__ = "step"

    step_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshot.snapshot_id"), nullable=False
    )
    step_natural_key: Mapped[str] = mapped_column(String, nullable=False)
    process_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("process.process_id"), nullable=False
    )
    # Self-reference stored as natural key, not FK, because the parser emits
    # parent refs before/after the child and may arrive out-of-order. Lookups
    # are done in application code against (snapshot_id, step_natural_key).
    parent_step_natural_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    step_level: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    step_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
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

    process: Mapped["Process"] = relationship(back_populates="steps")

    # Two complementary access paths matter here:
    # - ``process_id`` for "list every step of this process" (Step browser
    #   panel, lineage walks).
    # - ``(snapshot_id, step_natural_key)`` for parser-import dedup, same
    #   pattern as Process. Both created in alembic f1a8b3c5d207.
    __table_args__ = (
        Index("ix_step_process", "process_id"),
        Index("ix_step_snapshot_natural", "snapshot_id", "step_natural_key"),
    )
