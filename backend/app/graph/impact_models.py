from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String
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
