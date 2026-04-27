"""Logical template definition for column-level metadata extraction.

This template specifies the logical fields that describe columns, without any
reference to a particular SQL dialect or execution strategy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.metadata.templates.base import BaseTemplate


@dataclass
class ColumnTemplate(BaseTemplate):
    """Logical definition of a column metadata extraction template."""

    template_name: str = "column"
    description: str = (
        "Logical definition of technical column metadata within a table or view."
    )
    output_fields: List[str] = field(
        default_factory=lambda: [
            "schema_name",
            "table_name",
            "column_name",
            "data_type",
            "nullable",
            "ordinal_position",
        ]
    )
    required_filters: Optional[List[str]] = None
