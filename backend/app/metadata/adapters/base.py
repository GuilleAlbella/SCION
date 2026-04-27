"""Base interface for engine-specific metadata rendering adapters.

Adapters are responsible only for turning logical templates into SQL strings.
They are stateless and perform no I/O, execution, or environment inspection.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.metadata.templates.snapshot import SnapshotTemplate
from app.metadata.templates.schema import SchemaTemplate
from app.metadata.templates.table import TableTemplate
from app.metadata.templates.column import ColumnTemplate


class BaseAdapter(ABC):
    """Abstract base class for engine-specific metadata rendering adapters.

    Each adapter implements a fixed set of render methods, one per template
    type, and returns a SQL string describing a read-only metadata query.
    """

    @abstractmethod
    def render_snapshot(self, template: SnapshotTemplate) -> str:  # pragma: no cover - interface only
        """Render a logical snapshot template into a SQL string."""

    @abstractmethod
    def render_schema(self, template: SchemaTemplate) -> str:  # pragma: no cover - interface only
        """Render a logical schema template into a SQL string."""

    @abstractmethod
    def render_table(self, template: TableTemplate) -> str:  # pragma: no cover - interface only
        """Render a logical table/view template into a SQL string."""

    @abstractmethod
    def render_column(self, template: ColumnTemplate) -> str:  # pragma: no cover - interface only
        """Render a logical column template into a SQL string."""
