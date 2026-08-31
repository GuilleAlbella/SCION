"""OpenLineage adapter — Phase 2 stub.

PURPOSE
-------
Convert a Context Engine OpenLineage JSON payload into SCION's internal
``ParsedLineagePayload`` so the rest of the pipeline (noise_filter → ingestor)
runs unchanged.

WHAT IS NEEDED BEFORE THIS CAN BE IMPLEMENTED
----------------------------------------------
This adapter is blocked on the Teradata Product team (Context Engine) providing:

  1. A real sample JSON output from their parser.
     The OpenLineage spec (https://openlineage.io/spec/2-0-2/OpenLineage.json)
     defines the schema, but each implementation only populates a subset of
     fields.  We need to know *which* fields Context Engine actually emits.

  2. Confirmation of which ``Run.facets`` and ``Dataset.facets`` they use.
     Lineage detail (column-level, transformation type) lives in optional
     facets — ``ColumnLineageDatasetFacet``, ``SchemaDatasetFacet``, etc.
     Without a sample we cannot map those to ``ParsedAttributeLineage``.

  3. Clarification on how they identify Teradata databases/schemas.
     OpenLineage uses a ``namespace`` + ``name`` pair for datasets; we need
     to know the namespace convention (e.g. ``teradata://host:1025/DBNAME``
     or a short alias) to reconstruct our ``schema_name.object_name`` keys.

HOW TO IMPLEMENT (once the sample arrives)
------------------------------------------
  1. Wire OpenLineage ``RunEvent`` → ``ParsedLineagePayload``:
       - ``run.runId``            → ``parse_run_id``
       - ``eventTime``            → ``parse_timestamp``
       - ``job.namespace``        → ``platform.platform_natural_key``
       - ``inputs[*]``            → ``datasets`` (source nodes)
       - ``outputs[*]``           → ``datasets`` (target nodes)
       - ``inputs[*]`` → ``outputs[*]`` edges → ``dataset_lineage``
       - ``ColumnLineageDatasetFacet`` → ``attribute_lineage``
       - ``SchemaDatasetFacet``        → attributes / data types

  2. Derive ``container_natural_key`` from the dataset namespace URL so the
     schema snapshot matches what the Teradata dict-import already created.

  3. Add to ``REGISTERED_PARSERS`` at the bottom of this file once complete.

REGISTRATION (do not uncomment until implementation is done)
-------------------------------------------------------------
  # from app.parser_ingest.registry import register
  # register(OpenLineageParser())
"""

from __future__ import annotations

from typing import Any

from app.parser_ingest.base_parser import BaseLineageParser, LineageParserError
from app.parser_ingest.parser_models import ParsedLineagePayload


class OpenLineageParserError(LineageParserError):
    """Raised when an OpenLineage payload cannot be processed."""


class OpenLineageParser(BaseLineageParser):
    """Adapter for the OpenLineage JSON format emitted by Context Engine.

    NOT YET IMPLEMENTED — see module docstring for what is needed.
    """

    @property
    def technology(self) -> str:
        return "openlineage"

    def validate(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise OpenLineageParserError(
                f"OpenLineage payload must be a dict, got {type(payload).__name__}"
            )
        # Minimal OpenLineage envelope check (spec §2.0 RunEvent).
        for key in ("eventType", "eventTime", "run", "job"):
            if key not in payload:
                raise OpenLineageParserError(
                    f"Not a valid OpenLineage RunEvent — missing key: '{key}'"
                )

    def parse(self, payload: Any) -> ParsedLineagePayload:
        raise NotImplementedError(
            "OpenLineageParser.parse() is not implemented yet.\n"
            "Blocked on: Context Engine sample JSON from Teradata Product team.\n"
            "See module docstring for the full requirements."
        )
