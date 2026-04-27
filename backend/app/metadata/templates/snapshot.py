"""Logical template definition for snapshot metadata extraction.

This template describes *what* snapshot-related fields are expected in a
metadata query, independent of any concrete SQL or engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.metadata.templates.base import BaseTemplate


@dataclass
class SnapshotTemplate(BaseTemplate):
    """Logical definition of a snapshot extraction template."""

    template_name: str = "snapshot"
    description: str = (
        "Logical definition of snapshot metadata, including time and source system."
    )
    output_fields: List[str] = field(
        default_factory=lambda: [
            "snapshot_time",
            "source_system",
            "description",
        ]
    )
    required_filters: Optional[List[str]] = None
