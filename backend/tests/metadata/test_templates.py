"""Smoke tests for metadata template definitions.

These tests validate that templates are structurally well-defined and do not
embed any SQL or engine-specific details.
"""

from __future__ import annotations

from app.metadata.templates.column import ColumnTemplate
from app.metadata.templates.schema import SchemaTemplate
from app.metadata.templates.snapshot import SnapshotTemplate
from app.metadata.templates.table import TableTemplate


def test_templates_can_be_instantiated() -> None:
    """Each template should be instantiable with default values."""

    SnapshotTemplate()
    SchemaTemplate()
    TableTemplate()
    ColumnTemplate()


def test_output_fields_defined_and_non_empty() -> None:
    """Every template must define a non-empty list of logical output fields."""

    templates = [
        SnapshotTemplate(),
        SchemaTemplate(),
        TableTemplate(),
        ColumnTemplate(),
    ]

    for template in templates:
        assert hasattr(template, "output_fields"), "Template must have output_fields attribute"
        assert isinstance(template.output_fields, list), "output_fields must be a list"
        assert template.output_fields, "output_fields must not be empty"


def test_templates_do_not_contain_sql_strings() -> None:
    """Templates should not embed raw SQL or dialect-specific fragments.

    This test performs a simple heuristic check on logical field names to
    ensure they do not look like SQL fragments.
    """

    templates = [
        SnapshotTemplate(),
        SchemaTemplate(),
        TableTemplate(),
        ColumnTemplate(),
    ]

    for template in templates:
        combined = " ".join(str(f) for f in template.output_fields).lower()
        for forbidden in ("select", " from ", " join ", " where "):
            assert forbidden not in combined, "Templates must not contain SQL-like tokens in output_fields"
