"""Logical template definition for table and view metadata extraction.

This template specifies the logical fields that describe tables or views,
independent of any underlying database engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.metadata.templates.base import BaseTemplate


@dataclass
class TableTemplate(BaseTemplate):
    """Logical definition of a table or view extraction template."""

    template_name: str = "table"
    description: str = (
        "Logical definition of table or view metadata within a schema snapshot."
    )
    output_fields: List[str] = field(
        default_factory=lambda: [
            "schema_name",
            "table_name",
            "object_type",
        ]
    )
    required_filters: Optional[List[str]] = None
