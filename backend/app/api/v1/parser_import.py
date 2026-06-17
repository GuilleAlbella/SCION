from __future__ import annotations

"""Parser Import API (v1).

Accepts the DataDNA parser JSON feed and either:
- `dry_run=true`: analyzes the payload and returns a report WITHOUT persisting,
- `dry_run=false` (default): runs the full ingestion and returns the new
  snapshot_id + counts.

This endpoint is the integration seam between the parser team and SCION.
Until the parser calls our API directly, the frontend's "Import from
Parser" button reads a JSON file locally and POSTs it here.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query, status
from pydantic import BaseModel

from app.parser_ingest import teradata_parser, noise_filter, ingestor, dry_run
from app.parser_ingest.parser_models import IngestionReport


router = APIRouter(prefix="/parser-import", tags=["parser-import"])


class ImportResponse(BaseModel):
    """Flattened shape of `IngestionReport` for the API response.

    We flatten instead of returning the dataclass as-is so Swagger docs show
    each field explicitly — the frontend reads these to render the "what was
    ingested" panel after each import.
    """
    dry_run: bool
    snapshot_id: Optional[int]
    parse_run_id: str
    parse_timestamp: str
    input_counts: Dict[str, int]
    filtered_counts: Dict[str, int]
    persisted_counts: Dict[str, int]
    warnings: list[str]


def _report_to_response(r: IngestionReport) -> Dict[str, Any]:
    """Convert the internal dataclass to the JSON-friendly response."""
    return {
        "dry_run": r.dry_run,
        "snapshot_id": r.snapshot_id,
        "parse_run_id": r.parse_run_id,
        "parse_timestamp": r.parse_timestamp.isoformat(),
        "input_counts": r.input_counts,
        "filtered_counts": r.filtered_counts,
        "persisted_counts": r.persisted_counts,
        "warnings": r.warnings,
    }


@router.post(
    "/lineage",
    status_code=status.HTTP_200_OK,
    response_model=ImportResponse,
    summary="Import a DataDNA parser JSON lineage payload",
)
def import_lineage(
    payload: Dict[str, Any] = Body(..., description="Raw parser JSON payload"),
    dry_run_mode: bool = Query(
        default=True,
        alias="dry_run",
        description="If true (default), analyze and report but do not persist.",
    ),
    source_system: Optional[str] = Query(
        default=None,
        description="Override snapshot.source_system. Defaults to parser:<platform>.",
    ),
    description: Optional[str] = Query(
        default=None,
        description="Optional description stored on the snapshot row.",
    ),
    attach_to_snapshot_id: Optional[int] = Query(
        default=None,
        alias="snapshot_id",
        description=(
            "If provided, lineage is attached to this existing snapshot instead "
            "of creating a new one. Use after a dict import to produce a unified snapshot."
        ),
    ),
) -> Dict[str, Any]:
    """Ingest a parser lineage payload into SCION.

    The request flow is always the same three stages — the only difference
    is whether we persist at the end or produce a dry-run report:

        parse → noise_filter → (ingest | dry_run)
    """

    # ──── 1. Parse raw JSON into internal dataclasses ────
    try:
        parsed = teradata_parser.parse(payload)
    except teradata_parser.ParserPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid parser payload: {exc}",
        )
    except Exception as exc:  # unexpected — surface to caller for debugging
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to parse payload: {exc}",
        )

    # ──── 2. Apply noise filter (placeholders, literals) ────
    # Mutates `parsed` in place. Stats are stored on `parsed.stats`.
    noise_filter.apply(parsed)

    # ──── 3. Dry-run OR real ingestion ────
    if dry_run_mode:
        report = dry_run.analyze(parsed)
    else:
        report = ingestor.ingest(
            parsed,
            source_system=source_system,
            description=description,
            attach_to_snapshot_id=attach_to_snapshot_id,
        )

    return _report_to_response(report)
