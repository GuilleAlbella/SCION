"""Logical template definition for schema metadata extraction.

This template describes *what* schema-related fields are expected, without any
engine-specific SQL details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.metadata.templates.base import BaseTemplate


@dataclass
class SchemaTemplate(BaseTemplate):
    """Logical definition of a schema extraction template."""

    template_name: str = "schema"
    description: str = "Logical definition of schema metadata within a snapshot."
    output_fields: List[str] = field(
        default_factory=lambda: [
            "schema_name",
        ]
    )
    required_filters: Optional[List[str]] = None
