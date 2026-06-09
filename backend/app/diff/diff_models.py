from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Dict, Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


@dataclass(frozen=True)
class Change:
    """Immutable representation of a structural change between snapshots.

    v5.1 stores only enough information to be transportable and
    JSON-serializable; it has no persistence or behaviour attached.
    """

    object_type: str
    object_identifier: str
    change_type: str
    before_state: Optional[Dict]
    after_state: Optional[Dict]
    severity: str = "LOW"
    is_breaking: bool = False


class ChangeEvent(Base):
    """Persisted representation of a computed Change.

    v5.5 introduces this as an append-only, immutable audit log. It is not
    used to drive diff logic itself; it only records what was detected.

    Indexes (added in alembic revision d05a1b2c3d4e):

    - ``ix_change_event_snapshot_pair (snapshot_from, snapshot_to)``: every
      hot read on this table — the diff-details list, the idempotency probe
      inside ``DiffEngine.compute_diff``, the impact / DDL endpoints — filters
      by this pair. Without it, a 250k-row table forces a full scan per
      query, which on a multi-pair diff request stacks up to seconds of
      wasted CPU.
    - ``ix_change_event_snapshot_to (snapshot_to)``: backs Intelligence
      scorecard and domain-risk queries that filter only on snapshot_to
      (without a snapshot_from constraint). On a 1.8M-row table, a full
      scan on these governance queries added ~80 s of latency; this index
      brings them down to milliseconds.
    - ``ix_change_event_object_identifier (object_identifier)``: backs the
      ``/timeline`` and ``/objects/search`` endpoints, which both filter
      by object name. Substring (``ILIKE %q%``) won't use this index, but
      exact matches and prefix matches will, and the ``DISTINCT`` query in
      ``/objects/search`` benefits significantly.
    """

    __tablename__ = "change_event"

    change_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    snapshot_from: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_to: Mapped[int] = mapped_column(Integer, nullable=False)
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    object_identifier: Mapped[str] = mapped_column(String, nullable=False)
    change_type: Mapped[str] = mapped_column(String, nullable=False)
    before_state: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)
    after_state: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_breaking: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_change_event_snapshot_pair", "snapshot_from", "snapshot_to"),
        Index("ix_change_event_snapshot_to", "snapshot_to"),
        Index("ix_change_event_object_identifier", "object_identifier"),
    )

