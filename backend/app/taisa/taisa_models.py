from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


_ALLOWED_CHANGE_EVENT_KEYS = {
    "object_type",
    "object_identifier",
    "change_type",
    "before_state",
    "after_state",
}

_ALLOWED_CONTEXT_KEYS = {
    "source_system",
    "snapshot_time",
}

_ALLOWED_IMPACT_KEYS = {
    "object",
    "object_type",
    "impact_level",
    "depth",
}

_VALID_IMPACT_LEVELS = {"DIRECT", "INDIRECT"}


@dataclass
class TaisaImpactItem:
    """Single impact entry in the TAISA payload.

    This is the normalised, human-readable view of technical impact, built
    on top of graph/impact data. It uses only identifiers and enums, not
    internal IDs.
    """

    object: str
    object_type: str
    impact_level: str
    depth: int

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "TaisaImpactItem":
        # Strict key set
        keys = set(raw.keys())
        if keys != _ALLOWED_IMPACT_KEYS:
            raise ValueError(f"Unexpected keys in impact item: {keys}")

        impact_level = raw.get("impact_level")
        if impact_level not in _VALID_IMPACT_LEVELS:
            raise ValueError(f"Invalid impact_level: {impact_level!r}")

        depth = raw.get("depth")
        if not isinstance(depth, int) or depth < 1:
            raise ValueError("depth must be an integer >= 1")

        obj = raw.get("object")
        obj_type = raw.get("object_type")
        if not isinstance(obj, str) or not obj:
            raise ValueError("impact.object must be a non-empty string")
        if not isinstance(obj_type, str) or not obj_type:
            raise ValueError("impact.object_type must be a non-empty string")

        return cls(
            object=obj,
            object_type=obj_type,
            impact_level=impact_level,
            depth=depth,
        )

    def to_primitive(self) -> Dict[str, Any]:
        return {
            "object": self.object,
            "object_type": self.object_type,
            "impact_level": self.impact_level,
            "depth": self.depth,
        }


@dataclass
class TaisaAnalysisRequest:
    """Input payload for TAISA.

    This is a provider-agnostic description of what the Reasoning Engine
    receives. It intentionally avoids DB models and uses only primitive
    structures so that it can be logged, versioned, and replayed.
    """

    prompt_version: str
    change_event: Dict[str, Any]
    impacts: List[TaisaImpactItem]
    context: Dict[str, Any]

    @classmethod
    def from_raw(
        cls,
        *,
        prompt_version: str,
        change_event: Dict[str, Any],
        impacts: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> "TaisaAnalysisRequest":
        """Validate and normalise raw TAISA input structures.

        This enforces the 7.3 MVP contract:
        - change_event has required keys and no extras.
        - impacts is a list (possibly empty) of valid TaisaImpactItem.
        - context includes source_system and snapshot_time only.
        - before_state/after_state are JSON-serialisable.
        """

        if not isinstance(change_event, dict):
            raise ValueError("change_event must be a dict")
        if not isinstance(context, dict):
            raise ValueError("context must be a dict")
        if not isinstance(impacts, list):
            raise ValueError("impacts must be a list (can be empty)")

        # Strict keys for change_event
        ce_keys = set(change_event.keys())
        if ce_keys != _ALLOWED_CHANGE_EVENT_KEYS:
            raise ValueError(f"Unexpected keys in change_event: {ce_keys}")

        # Minimal structural checks
        for key in ("object_type", "object_identifier", "change_type"):
            value = change_event.get(key)
            if not isinstance(value, str) or not value:
                raise ValueError(f"change_event.{key} must be a non-empty string")

        # JSON-serialisability for before_state / after_state
        import json

        for state_key in ("before_state", "after_state"):
            try:
                json.dumps(change_event.get(state_key))
            except TypeError as exc:  # pragma: no cover - defensive branch
                raise ValueError(
                    f"change_event.{state_key} must be JSON-serialisable"
                ) from exc

        # Strict keys for context
        ctx_keys = set(context.keys())
        if ctx_keys != _ALLOWED_CONTEXT_KEYS:
            raise ValueError(f"Unexpected keys in context: {ctx_keys}")

        if not isinstance(context.get("source_system"), str) or not context.get(
            "source_system"
        ):
            raise ValueError("context.source_system must be a non-empty string")
        if not isinstance(context.get("snapshot_time"), str) or not context.get(
            "snapshot_time"
        ):
            raise ValueError("context.snapshot_time must be a non-empty ISO string")

        impact_items = [TaisaImpactItem.from_raw(raw) for raw in impacts]

        return cls(
            prompt_version=prompt_version,
            change_event={
                "object_type": change_event["object_type"],
                "object_identifier": change_event["object_identifier"],
                "change_type": change_event["change_type"],
                "before_state": change_event.get("before_state"),
                "after_state": change_event.get("after_state"),
            },
            impacts=impact_items,
            context={
                "source_system": context["source_system"],
                "snapshot_time": context["snapshot_time"],
            },
        )

    def to_primitive(self) -> Dict[str, Any]:
        """Return a JSON-serialisable view of the request."""

        return {
            "prompt_version": self.prompt_version,
            "change_event": self.change_event,
            "impact": [item.to_primitive() for item in self.impacts],
            "context": self.context,
        }


@dataclass
class TaisaAnalysisResult:
    """Minimal contract for TAISA's response.

    The structure is intentionally generic; higher layers are responsible
    for interpreting fields such as severity or recommended actions.
    """

    # Correlation fields (may be None for the normalised contract-only flow).
    change_id: Optional[int]
    snapshot_id: Optional[int]

    # TAISA response model (v7.5) — always populated in the stub client.
    classification: str
    risk_level: str
    recommendations: List[str]
    explanation: str

    # Raw provider response / debug payload.
    summary: str
    raw_response: Dict[str, Any]


class ReasoningEvent(Base):
    """ ORM model for persisted TAISA reasoning events.

    This is an append-only log of reasoning results for a given change.
    No business logic or update/delete behaviour is defined here.
    """

    __tablename__ = "reasoning_event"

    reasoning_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    change_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    taisa_version: Mapped[str] = mapped_column(String, nullable=False)
    classification: Mapped[str] = mapped_column(String, nullable=False)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)
    recommendations: Mapped[dict] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
