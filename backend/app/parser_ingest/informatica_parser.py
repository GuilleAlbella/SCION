"""Informatica (ETL) adapter — Phase 2B stub.

PURPOSE
-------
Convert an Informatica lineage export into SCION's internal
``ParsedLineagePayload``.

DESIGN NOTE — Generic ETL interface
------------------------------------
Per Chris Pilon's direction (Reunion 32), this must NOT be Informatica-specific.
The goal is a generic ETL adapter pattern where Informatica is the first
implementation.  Future implementations (DataStage, Talend, dbt, …) extend
the same ``BaseLineageParser`` without any changes to the ingestor.

The concrete mapping from ETL tool → ``ParsedLineagePayload`` will differ per
tool, but the *contract* is always the same.

WHAT IS NEEDED BEFORE THIS CAN BE IMPLEMENTED
----------------------------------------------
This adapter is blocked on Jon Brightling providing:

  1. Which Informatica product / version the target accounts run.
       - PowerCenter (classic XML-based workflow):
           exports via Repository Manager or pmrep CLI as XML.
       - IICS / Cloud Data Integration:
           REST API or Informatica Metadata API (OpenAPI), returns JSON.
       - IDQ (Data Quality): different metadata model entirely.

  2. A sample export file or API response from one of those.
     Without a sample the field mapping below cannot be written.

  3. The level of lineage detail available:
       - Table-to-table only (dataset_lineage)?
       - Column-to-column with transformations (attribute_lineage)?
     This determines how much of ``ParsedLineagePayload`` we can populate.

  4. Whether the Informatica environment is on-premises or cloud.
     On-prem PowerCenter requires a local pmrep/infacmd extraction script;
     cloud IICS can be polled via REST with a service-account token.

HOW TO IMPLEMENT (once the sample arrives)
------------------------------------------
  PowerCenter XML path (most likely for existing large accounts):
    1. Parse the repository XML: ``<SOURCE>``, ``<TARGET>`` → datasets.
    2. ``<CONNECTOR>`` mappings → ``dataset_lineage`` edges.
    3. ``<TRANSFORMFIELD>`` blocks → ``attribute_lineage`` edges (if available).
    4. Normalise names to ``SCHEMA.OBJECT_NAME`` upper-case convention so
       they match nodes already created by the Teradata dict-import.

  IICS REST path (newer accounts):
    1. Call ``/v3/projects/{projectId}/flows`` → flow list.
    2. For each flow, call ``/v3/flows/{id}/lineage`` → source/target pairs.
    3. Map to ``ParsedLineagePayload`` following the same schema above.

  In both cases, wrap the adapter as ``InformaticaLineageParser(BaseLineageParser)``
  so the ingestor can call ``parser.safe_parse(payload)`` without knowing the
  source technology.

REGISTRATION (do not uncomment until implementation is done)
-------------------------------------------------------------
  # from app.parser_ingest.registry import register
  # register(InformaticaLineageParser())
"""

from __future__ import annotations

from typing import Any

from app.parser_ingest.base_parser import BaseLineageParser, LineageParserError
from app.parser_ingest.parser_models import ParsedLineagePayload


class InformaticaParserError(LineageParserError):
    """Raised when an Informatica export payload cannot be processed."""


class InformaticaLineageParser(BaseLineageParser):
    """Adapter for Informatica ETL lineage exports.

    Serves as the reference implementation for the generic ETL adapter pattern.
    DataStage, dbt, Talend, etc. would follow the same structure.

    NOT YET IMPLEMENTED — see module docstring for what is needed.
    """

    @property
    def technology(self) -> str:
        # Override with "datastage", "dbt", etc. for other ETL adapters.
        return "informatica"

    def validate(self, payload: Any) -> None:
        # Placeholder — real validation depends on the export format
        # (XML dict for PowerCenter, JSON dict for IICS).
        if payload is None:
            raise InformaticaParserError("Informatica payload must not be None")

    def parse(self, payload: Any) -> ParsedLineagePayload:
        raise NotImplementedError(
            "InformaticaLineageParser.parse() is not implemented yet.\n"
            "Blocked on: export format sample from Jon Brightling.\n"
            "See module docstring for the full requirements."
        )
