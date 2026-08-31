"""Base interface for external lineage-parser adapters.

SCION can receive lineage data from multiple upstream sources, each with its
own wire format:

  - Teradata/DataDNA parser  → our custom JSON (already in production)
  - Context Engine           → OpenLineage JSON  (Phase 2, pending sample)
  - Informatica PowerCenter  → TBD               (Phase 2B, pending Jon)

All adapters map their source format to the same internal ``ParsedLineagePayload``
so the rest of the pipeline (noise_filter → ingestor) stays unchanged.

Compare with ``app.metadata.adapters.base.BaseAdapter`` which does the same
for metadata *extraction* (SQL rendering).  This base class does the equivalent
for lineage *ingestion* (external payload → internal model).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.parser_ingest.parser_models import ParsedLineagePayload


class BaseLineageParser(ABC):
    """Abstract base for all external lineage-parser adapters.

    Subclasses convert a raw payload (dict, string, file path, or whatever
    the source technology produces) into a ``ParsedLineagePayload``.

    Subclasses MUST implement:
        - ``technology``: short identifier, e.g. ``"teradata"``, ``"informatica"``
        - ``parse(payload)``: the conversion entry point

    Subclasses MAY override:
        - ``validate(payload)``: pre-parse sanity check; raise
          ``LineageParserError`` on failure.  Called by ``safe_parse()``
          before ``parse()``.
    """

    @property
    @abstractmethod
    def technology(self) -> str:
        """Short lower-case identifier for this parser's source technology."""

    @abstractmethod
    def parse(self, payload: Any) -> ParsedLineagePayload:
        """Convert a raw external payload into ``ParsedLineagePayload``.

        Args:
            payload: The raw input — type varies by adapter:
                     - dict for JSON-based sources (Teradata parser, OpenLineage)
                     - str/Path for file-based sources (Informatica XML export)

        Returns:
            A validated ``ParsedLineagePayload`` ready for noise_filter + ingestor.

        Raises:
            LineageParserError: when the payload is structurally unusable.
        """

    def validate(self, payload: Any) -> None:  # noqa: ARG002
        """Optional pre-parse validation hook.

        Override to perform cheap structural checks before the full parse.
        Default implementation is a no-op.

        Raises:
            LineageParserError: if the payload fails validation.
        """

    def safe_parse(self, payload: Any) -> ParsedLineagePayload:
        """Run ``validate`` then ``parse``; always raises ``LineageParserError``.

        Convenience wrapper so callers get a single entry point that normalises
        errors from both stages into one exception type.
        """
        self.validate(payload)
        return self.parse(payload)


class LineageParserError(ValueError):
    """Raised when a parser adapter cannot process its input payload.

    Use this (or a subclass) instead of bare ``ValueError`` so callers can
    catch all adapter errors with a single ``except LineageParserError``.
    """
