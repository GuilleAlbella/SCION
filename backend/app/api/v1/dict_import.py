from __future__ import annotations

"""Data dictionary import endpoint.

Accepts the 6-file batch Rahul's extractor produces (databases /
tables / columns / indices / partitioning / tabletext) and persists
them as one SCION snapshot keyed by `extract_run_id`.

The endpoint is **format-agnostic at the wire level** — files are
received as multipart upload regardless of extension. The format
detector classifies each file by content (and filename as tiebreaker)
before routing to the right reader. This is the design we agreed on
in Meeting #8 follow-ups: one endpoint, content-based dispatch, ready
for whatever Rahul standardises on long-term (.dat or JSON).

Validation order (fail fast on the cheapest check):
  1. At least one file uploaded.
  2. Each file is detected as a known dict view; reject UNKNOWN with
     a 400 listing the file + reason.
  3. Each file parses successfully (reader raises DictFlatFileError
     on layout mismatch).
  4. All files share the same (source_system_name, extract_run_id);
     reject with 400 + a diff describing who disagreed.
  5. Persist as one snapshot. Returns counts in the response.
"""

from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.metadata import (
    dict_flat_file_reader,
    dict_batch_validator,
    dict_persister,
    format_detector,
)
from app.metadata.format_detector import ContentType, Format


router = APIRouter(prefix="/dict-import", tags=["dict-import"])


# ──── Response shape ────

class DictImportResponse(BaseModel):
    """What we send back after a successful (or no-op) import.

    `_seen` fields are the raw counts in Rahul's batch; `_created`
    are how many landed in SCION's DB. Drift between the two means
    records referenced parents we didn't ingest (typical for system
    tables in DBC.* that aren't in `tables.dat`).
    """
    snapshot_id: int
    skipped_existing: bool
    source_system_name: str
    extract_run_id: str
    schemas_created: int
    tables_created: int
    columns_created: int
    indices_created: int
    partitioning_created: int
    ddl_text_created: int
    indices_seen: int
    partitioning_seen: int
    tabletext_seen: int
    files_received: int


# ──── Helpers ────

def _read_for_content_type(content: bytes, ct: ContentType, filename: str):
    """Dispatch to the correct reader based on detected content-type.

    Each branch decodes the bytes once and hands a Path-like buffer
    to the reader. We pass through a temp file so the reader API
    (which takes Path) doesn't have to grow a "from string" overload —
    keeps the unit-test surface narrow.
    """
    import tempfile
    from pathlib import Path

    # Multipart already gave us bytes. Persist to a temp file so the
    # readers can stay Path-based (cleaner unit-test contract). The
    # files are tiny relative to a request lifecycle — no streaming
    # benefit lost.
    with tempfile.NamedTemporaryFile(
        delete=False, suffix=".dat", mode="wb"
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        if ct is ContentType.DICT_DATABASES:
            return ("databases", dict_flat_file_reader.read_databases(tmp_path))
        if ct is ContentType.DICT_TABLES:
            return ("tables", dict_flat_file_reader.read_tables(tmp_path))
        if ct is ContentType.DICT_COLUMNS:
            return ("columns", dict_flat_file_reader.read_columns(tmp_path))
        if ct is ContentType.DICT_INDICES:
            return ("indices", dict_flat_file_reader.read_indices(tmp_path))
        if ct is ContentType.DICT_PARTITIONING:
            return ("partitioning", dict_flat_file_reader.read_partitioning(tmp_path))
        if ct is ContentType.DICT_TABLETEXT:
            return ("tabletext", dict_flat_file_reader.read_tabletext(tmp_path))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File `{filename}` was detected as `{ct.value}`, "
                   f"which isn't a dict-import content type.",
        )
    finally:
        # Cleanup is best-effort — if Windows holds the file briefly
        # after read, the OS will reclaim on next reboot. We don't
        # want to fail the request over a temp-file lock.
        try:
            tmp_path.unlink()
        except OSError:
            pass


# ──── The endpoint ────

@router.post("", response_model=DictImportResponse)
async def import_dict_batch(
    files: List[UploadFile] = File(
        ...,
        description=(
            "1 to 6 dict extract files in any combination. The endpoint "
            "auto-detects which view each file represents. Filenames "
            "matching Rahul's templates (e.g. `tablesv_full_export.rendered.dat`) "
            "are detected with high confidence."
        ),
    ),
    force: bool = Form(
        False,
        description=(
            "If true, ignore an existing snapshot with the same "
            "extract_run_id and create a duplicate. Useful for testing "
            "the pipeline; do NOT use in production."
        ),
    ),
) -> DictImportResponse:
    """Accept up to 6 dict files in one request and persist as a snapshot.

    The batch must internally reference the same extraction run
    (`source_system_name` + `extract_run_id`). Files can arrive in
    any order; we route by content-type detection, not multipart
    field position.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded. Send at least one dict extract file.",
        )

    # Detect, parse, group by category. Errors at this stage are
    # 400-class (caller's fault — bad file or wrong contract).
    parsed_by_category: dict[str, list] = {
        "databases": [], "tables": [], "columns": [],
        "indices": [], "partitioning": [], "tabletext": [],
    }
    files_for_validator: list[tuple[str, list]] = []

    for upload in files:
        content = await upload.read()
        verdict = format_detector.detect(content, filename=upload.filename or "")

        if verdict.format is Format.UNKNOWN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"File `{upload.filename}` could not be classified: "
                    f"{verdict.reason}"
                ),
            )
        if verdict.content_type is ContentType.UNKNOWN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"File `{upload.filename}` is a {verdict.format.value} "
                    f"but content type couldn't be determined: {verdict.reason}"
                ),
            )

        try:
            category, records = _read_for_content_type(
                content, verdict.content_type, upload.filename or ""
            )
        except dict_flat_file_reader.DictFlatFileError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Parse error in `{upload.filename}`: {e}",
            )

        parsed_by_category[category].extend(records)
        files_for_validator.append((upload.filename or category, records))

    # Cross-file consistency: same source_system + extract_run_id
    # across every record of every file.
    try:
        identity = dict_batch_validator.validate_batch(files_for_validator)
    except dict_batch_validator.BatchConsistencyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Persist. Caller-owned commit so we can roll back on the rare
    # database error without leaving a partial snapshot.
    with Session(bind=engine) as session:
        try:
            result = dict_persister.persist_batch(
                session=session,
                identity=identity,
                databases=parsed_by_category["databases"],
                tables=parsed_by_category["tables"],
                columns=parsed_by_category["columns"],
                indices=parsed_by_category["indices"],
                partitioning=parsed_by_category["partitioning"],
                tabletext=parsed_by_category["tabletext"],
                force=force,
            )
            session.commit()
        except Exception as e:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to persist snapshot: {e}",
            )

    # Run the post-ingest analytical pipeline so the new snapshot
    # shows up in /graph, /metrics, /usage, /intelligence, /lineage
    # and /impact. Skipped on idempotent re-imports — the prior run
    # already populated everything, re-running would be wasted work.
    if not result.skipped_existing:
        dict_persister.run_post_ingest_pipeline(result.snapshot_id)

    return DictImportResponse(
        snapshot_id=result.snapshot_id,
        skipped_existing=result.skipped_existing,
        source_system_name=identity.source_system_name,
        extract_run_id=identity.extract_run_id,
        schemas_created=result.schemas_created,
        tables_created=result.tables_created,
        columns_created=result.columns_created,
        indices_created=result.indices_created,
        partitioning_created=result.partitioning_created,
        ddl_text_created=result.ddl_text_created,
        indices_seen=result.indices_seen,
        partitioning_seen=result.partitioning_seen,
        tabletext_seen=result.tabletext_seen,
        files_received=len(files),
    )
