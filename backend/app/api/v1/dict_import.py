from __future__ import annotations

"""Data dictionary import endpoint.

Accepts the 6-file batch Rahul's extractor produces (databases /
tables / columns / indices / partitioning / tabletext) and persists
them as one SCION snapshot keyed by `extract_run_id`.

The endpoint is **format-agnostic at the wire level** — files are
received as multipart upload regardless of extension. The format
detector classifies each file by content (and filename as tiebreaker)
before routing to the right reader.

Streaming pipeline (v1.14.09): every file is streamed to a temp file
on disk in 4-MiB chunks rather than `await upload.read()`-ed into
memory. The large views (columns, indices) are then parsed via
generator readers and persisted with batched
`bulk_insert_mappings` so neither parsed records nor ORM identity-map
grow unbounded. This is what makes a 9.8M-row / 1.9 GB columns file
ingestable on a laptop.

Validation order (fail fast on the cheapest check):
  1. At least one file uploaded.
  2. Each file is detected as a known dict view; reject UNKNOWN with
     a 400 listing the file + reason.
  3. Identity check: peek the first record of every file and verify
     they all share the same (source_system_name, extract_run_id).
  4. Persist as one snapshot. Returns counts in the response.
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


# ──── Streaming knobs ────
# 4 MiB chunks balance syscall overhead against memory footprint. At
# this size a 2 GB upload is 512 chunks — well below any practical
# overhead, and a single chunk is small enough that it won't blow up
# RAM even on a constrained box.
_UPLOAD_CHUNK_SIZE = 4 * 1024 * 1024
# Format detection only needs the file head. 64 KiB is plenty —
# detector inspects at most the first 8 KB but we keep some margin
# for files with unusual whitespace/BOM padding.
_DETECTION_HEAD_SIZE = 64 * 1024


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


# ──── Streaming helpers ────

async def _stream_upload_to_disk(upload: UploadFile) -> Path:
    """Persist an UploadFile to a NamedTemporaryFile in 4-MiB chunks.

    Why not `await upload.read()`: that returns the entire file as a
    single bytes object. For Rahul's full Transcend-DevTest extract
    that's 1.9 GB held in Python heap memory before parsing even
    begins — unworkable on a laptop and silly on a server. Streaming
    keeps RAM bounded at a single chunk regardless of file size.

    The caller is responsible for unlinking the returned path once
    parsing is done.
    """
    fd, tmp_name = tempfile.mkstemp(suffix=".dat")
    os.close(fd)
    tmp_path = Path(tmp_name)
    with tmp_path.open("wb") as out:
        while True:
            chunk = await upload.read(_UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            out.write(chunk)
    return tmp_path


def _detect_path(path: Path, filename: str):
    """Run format_detector against the head of a file on disk.

    The detector is content-only — it only looks at the first few KB.
    Reading just the head keeps detection cheap regardless of file
    size; loading the whole 1.9 GB columns file just to detect that
    it's flat-file would defeat the entire streaming refactor.
    """
    with path.open("rb") as f:
        head = f.read(_DETECTION_HEAD_SIZE)
    return format_detector.detect(head, filename=filename)


def _content_type_to_category(ct: ContentType) -> Optional[str]:
    """Translate the enum into the persister's category bucket name.

    Returns None for content types this endpoint doesn't accept (e.g.
    parser JSON), letting the caller raise a clean 400 instead of
    routing it to the wrong pipeline.
    """
    return {
        ContentType.DICT_DATABASES: "databases",
        ContentType.DICT_TABLES: "tables",
        ContentType.DICT_COLUMNS: "columns",
        ContentType.DICT_INDICES: "indices",
        ContentType.DICT_PARTITIONING: "partitioning",
        ContentType.DICT_TABLETEXT: "tabletext",
    }.get(ct)


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

    # ──── Step 1: stream every upload to disk + classify by content ────
    # Paths are kept by category so multiple files of the same view
    # would overwrite each other deliberately (only one
    # `columnsv_*.dat` per batch is the contract). The temp files are
    # cleaned up in the `finally` at the end of the handler.
    temp_paths: List[Path] = []
    paths_by_category: Dict[str, Path] = {}
    filenames_by_category: Dict[str, str] = {}

    try:
        for upload in files:
            tmp_path = await _stream_upload_to_disk(upload)
            temp_paths.append(tmp_path)

            verdict = _detect_path(tmp_path, upload.filename or "")

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

            category = _content_type_to_category(verdict.content_type)
            if category is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"File `{upload.filename}` was detected as "
                        f"`{verdict.content_type.value}`, which isn't a "
                        "dict-import content type."
                    ),
                )

            paths_by_category[category] = tmp_path
            filenames_by_category[category] = upload.filename or category

        # ──── Step 2: parse the small views eagerly (fits in memory) ────
        # databases ≤ 50k rows, tables ≤ 500k, partitioning ≤ 50k —
        # well under any memory pressure. tabletext can hit hundreds of
        # MB for a large EDW but its 9-field ENDREC layout doesn't
        # have a streaming reader yet (see tabletext TODO in reader);
        # in practice it's still small relative to columns.
        try:
            databases = (
                dict_flat_file_reader.read_databases(paths_by_category["databases"])
                if "databases" in paths_by_category else []
            )
            tables = (
                dict_flat_file_reader.read_tables(paths_by_category["tables"])
                if "tables" in paths_by_category else []
            )
            partitioning = (
                dict_flat_file_reader.read_partitioning(
                    paths_by_category["partitioning"]
                )
                if "partitioning" in paths_by_category else []
            )
            tabletext = (
                dict_flat_file_reader.read_tabletext(paths_by_category["tabletext"])
                if "tabletext" in paths_by_category else []
            )
        except dict_flat_file_reader.DictFlatFileError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Parse error: {e}",
            )

        # ──── Step 3: identity validation ────
        # Walk the in-memory lists for the small views, plus peek the
        # first record of the streamed views (columns, indices). This
        # keeps the temporal/identity checks O(small files) without
        # blowing up on the multi-GB columns file. Rahul's contract
        # guarantees identity is uniform within a single file — we
        # rely on parser-side arity validation to catch mid-file
        # corruption rather than walking 9.8M rows twice.
        validator_input: List[Tuple[str, list]] = []
        for cat, records in (
            ("databases", databases), ("tables", tables),
            ("partitioning", partitioning), ("tabletext", tabletext),
        ):
            if records:
                validator_input.append((filenames_by_category.get(cat, cat), records))

        for cat, iter_fn in (
            ("columns", dict_flat_file_reader.iter_columns),
            ("indices", dict_flat_file_reader.iter_indices),
        ):
            if cat in paths_by_category:
                try:
                    sample = dict_batch_validator.peek_first_record(
                        paths_by_category[cat], iter_fn,
                    )
                except dict_flat_file_reader.DictFlatFileError as e:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Parse error in `{filenames_by_category[cat]}`: {e}"
                        ),
                    )
                if sample is not None:
                    validator_input.append(
                        (filenames_by_category[cat], [sample]),
                    )

        try:
            identity = dict_batch_validator.validate_batch(validator_input)
        except dict_batch_validator.BatchConsistencyError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        # ──── Step 4: persist (streaming columns + indices) ────
        # We pass the generators directly to `persist_batch`. The
        # persister consumes them in chunks via
        # `bulk_insert_mappings`, never materialising more than one
        # batch worth of records at a time.
        columns_iter = (
            dict_flat_file_reader.iter_columns(paths_by_category["columns"])
            if "columns" in paths_by_category else iter(())
        )
        indices_iter = (
            dict_flat_file_reader.iter_indices(paths_by_category["indices"])
            if "indices" in paths_by_category else iter(())
        )

        with Session(bind=engine) as session:
            try:
                result = dict_persister.persist_batch(
                    session=session,
                    identity=identity,
                    databases=databases,
                    tables=tables,
                    columns=columns_iter,
                    indices=indices_iter,
                    partitioning=partitioning,
                    tabletext=tabletext,
                    force=force,
                )
                session.commit()
            except dict_flat_file_reader.DictFlatFileError as e:
                # Mid-stream parse error from the generators surfaces
                # as a clean 400 rather than a 500.
                session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Parse error during persist: {e}",
                )
            except Exception as e:
                session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to persist snapshot: {e}",
                )

        # ──── Step 5: post-ingest analytical pipeline ────
        # Skipped on idempotent re-imports — the prior run already
        # populated everything, re-running would be wasted work.
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

    finally:
        # Best-effort cleanup of the streamed-to-disk temp files.
        # On Windows the OS may briefly hold a file handle open after
        # close; we don't fail the request over a temp-file unlink.
        for p in temp_paths:
            try:
                p.unlink()
            except OSError:
                pass
