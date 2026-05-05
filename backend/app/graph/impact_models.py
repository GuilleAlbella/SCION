from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ImpactEvent(Base):
    """Persisted representation of an impact analysis result.

    v6.6 stores events as an append-only log; no business semantics or
    severity classification are applied at this stage.
    """

    __tablename__ = "impact_event"

    impact_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    change_id: Mapped[int] = mapped_column(Integer, nullable=False)
    impacted_node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    impact_level: Mapped[str] = mapped_column(String, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_id: Mapped[int] = mapped_column(Integer, nullable=False)
    impact_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ChangeImpactSummary(Base):
    """Pre-aggregated per-change impact counts.

    Why this table exists
    ---------------------
    The original ``POST /impact/batch`` endpoint computed downstream and
    upstream graph walks for every change in a diff at request time. On
    a 250k-change Transcend extract that meant 500k recursive-CTE walks
    over a 337k-edge graph; the request hung the browser at 5+ minutes.

    From v1.18 onwards, the post-ingest pipeline pre-aggregates these
    counts into this table — one row per ``change_id`` — so the batch
    endpoint becomes a simple paginated read. The single-change
    drill-down (``POST /impact/{change_id}``) still computes the full
    walk on demand because the detailed list of impacted nodes isn't
    persisted here.

    Schema notes
    ------------
    - ``change_id`` is the primary key (1:1 with ``ChangeEvent``). FK
      is intentional but ``ON DELETE CASCADE`` is NOT declared at the
      DB level; we rely on the Python-side cascade in
      ``snapshots.delete`` for consistency with the other dependent
      tables.
    - ``snapshot_id`` is the change's ``snapshot_to`` (the post-change
      topology where the impact was computed). Indexed for the batch
      read path which filters by snapshot.
    - ``max_depth`` records the deepest hop reached during the walk.
      Useful for spotting changes that ripple unusually far without
      having to re-run the analysis.
    """

    __tablename__ = "change_impact_summary"

    change_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("change_event.change_id"),
        primary_key=True,
    )
    snapshot_id: Mapped[int] = mapped_column(Integer, nullable=False)
    direct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indirect_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    impact_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_change_impact_summary_snapshot", "snapshot_id"),
    )
