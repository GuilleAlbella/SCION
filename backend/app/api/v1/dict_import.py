from __future__ import annotations

"""Data dictionary import endpoint.

Accepts the 6-file batch Rahul's extractor produces (databases /
tables / columns / indices / partitioning / tabletext) and persists
them as one SCION snapshot keyed by `extract_run_id`.

As of v1.21.6 (Pipeline 3, PR-D) the same endpoint also accepts the
2 PDCR usage extracts (`pdcr_log_*.dat`, `pdcr_object_usage_*.dat`).
Files are partitioned by content type after detection: dict files
flow through the existing snapshot pipeline (parse / validate /
persist / post-ingest); PDCR files are persisted afterwards via the
usage persisters, resolving object identifiers case-insensitively
against the just-created snapshot. A dict-only batch is fully
supported (existing behaviour); a PDCR-only batch is rejected with
a clean 400 because PDCR rows have no snapshot to resolve against.

PR-E (Pipeline 3) re-runs ``compute_criticality(usage_available=
True)`` after PDCR object_usage rows land, so the criticality cache
reflects real query/access counts instead of the graph-only
fallback the post-ingest pipeline writes. The re-compute is gated
on ``obj_result.inserted > 0`` and is best-effort (failures are
logged but don't fail the import — the dict snapshot already
committed).

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

import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.metadata import (
    dict_flat_file_reader,
    dict_batch_validator,
    dict_persister,
    format_detector,
)
from app.metadata import pdcr_flat_file_reader
from app.metadata.format_detector import ContentType, Format
from app.usage import pdcr_persister
from app.usage.criticality_engine import compute_criticality
from app.api.v1 import import_progress


router = APIRouter(prefix="/dict-import", tags=["dict-import"])
logger = logging.getLogger(__name__)


def _fmt_time(seconds: float) -> str:
    """Pretty-print a duration: <1s as ms, <60s as 'X.XXs', else 'Xm YYs'."""
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}m {s:05.2f}s"


def _fmt_bytes(n: int) -> str:
    """Pretty-print a byte count."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"


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
    # ──── PDCR routing (Pipeline 3, PR-D) ────
    # All optional / default 0 so callers that only upload dict files
    # see the same response shape they've always seen. The fields land
    # in the response payload when the mixed-batch route persists
    # `pdcr_log_*.dat` / `pdcr_object_usage_*.dat` alongside the dict.
    dbql_inserted: int = 0
    dbql_skipped_duplicate: int = 0
    dbql_skipped_invalid: int = 0
    object_usage_inserted: int = 0
    object_usage_skipped_unmapped_type: int = 0
    object_usage_skipped_orphan: int = 0
    object_usage_skipped_invalid: int = 0
    # Per-PDCR-type count of unmapped-type skips (e.g. {"UDF": 54, "SP": 22}).
    # Surfaced so operators see exactly what coverage we're missing —
    # FR-13 graceful out-of-scope handling.
    object_usage_skipped_by_type: Dict[str, int] = {}
    # Snapshot used for case-insensitive resolution of object_usage
    # rows. Defaults to the snapshot just created from the same batch;
    # falls back to the most recent existing snapshot when this batch
    # contains only PDCR files; None when there's no snapshot at all
    # (every row is then accepted blindly).
    pdcr_resolved_against_snapshot_id: Optional[int] = None
    # ──── Criticality re-compute (Pipeline 3, PR-E) ────
    # The post-ingest pipeline calls ``compute_criticality(usage_available=
    # False)`` because at that moment no PDCR usage rows exist yet for
    # the snapshot. After PR-D wires PDCR ingest into the same request,
    # we re-run it with ``usage_available=True`` so the criticality
    # cache reflects real query/access counts instead of pure graph
    # fragility. ``criticality_recomputed`` is True when the second
    # pass ran; the three count fields are the resulting HIGH /
    # MEDIUM / LOW totals so the response surfaces what the operator
    # would otherwise have to fetch from /usage/criticality.
    criticality_recomputed: bool = False
    criticality_high_count: int = 0
    criticality_medium_count: int = 0
    criticality_low_count: int = 0


# ──── Streaming helpers ────

def _stream_upload_to_disk(upload: UploadFile) -> Path:
    """Persist an UploadFile to a NamedTemporaryFile in 4-MiB chunks.

    Why not `upload.file.read()` (no chunks): that returns the entire
    file as a single bytes object. For Rahul's full Transcend-DevTest
    extract that's 1.9 GB held in Python heap memory before parsing
    even begins — unworkable on a laptop and silly on a server.
    Chunked streaming keeps RAM bounded at a single chunk regardless
    of file size.

    Why sync (not `async def` + `await upload.read()`): the parent
    handler is `def`, not `async def`, because the heavy work
    (parse + persist + post-ingest) is all synchronous and blocking
    it inside an async handler would freeze the event loop —
    starving the parallel `/progress` and `/cancel` requests for
    minutes. Reading from `upload.file` (the underlying
    `SpooledTemporaryFile`) is the sync equivalent of
    `await upload.read()` and works identically.

    The caller is responsible for unlinking the returned path once
    parsing is done.
    """
    fd, tmp_name = tempfile.mkstemp(suffix=".dat")
    os.close(fd)
    tmp_path = Path(tmp_name)
    with tmp_path.open("wb") as out:
        while True:
            chunk = upload.file.read(_UPLOAD_CHUNK_SIZE)
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


def _apply_bulk_insert_pragmas(session: Session) -> Dict[str, str]:
    """Switch SQLite to fast-bulk-insert mode for the duration of one ingest.

    The default `PRAGMA synchronous = FULL` makes SQLite fsync after
    every commit — and `bulk_insert_mappings` commits once per batch.
    For 9.8M-row workloads that's ~2 000 fsyncs serialised by Windows'
    write-through layer, and we measured the disk pegged at ~0.7 MB/s
    even on local NVMe. Relaxing to `synchronous = OFF` removes the
    per-batch fsync entirely; we've measured 3-5× speedup on the
    persist phase with no correctness change.

    Why we DON'T also flip `journal_mode = MEMORY` here (we used to,
    until v1.14.16): switching journal_mode out of WAL on this
    connection re-enables SQLite's writer-blocks-readers locking. The
    moment that's enabled, the parallel `/progress` polls and any
    other reads stall the persist writer instead of running
    concurrently — we measured a 3× regression in persist wall time
    on the Transcend-DevTest extract once the polling started
    actually working. WAL (set globally on the engine connect event)
    is the right journal mode for our mixed read+write workload.

    Trade-off: an OS-level crash mid-ingest can corrupt the WAL file
    (so the last commit may not be recoverable). We accept that here
    because:
      - The endpoint runs the whole import in one logical transaction;
        a crash means "no snapshot was created" semantically, and the
        user re-runs.
      - SCION today is a dev/demo workload on a single laptop; durability
        becomes the deployment story's problem (Postgres / WAL replication
        / backups), not SQLite's.

    Returns a dict of the previous values so callers can restore them
    via `_restore_pragmas` regardless of how the transaction ended.
    Capturing the originals (instead of hard-coding "NORMAL") means we
    honour whatever the engine was configured with — if a future
    migration tunes SQLite globally, this helper still round-trips
    correctly.
    """
    previous = {
        "synchronous": str(session.execute(text("PRAGMA synchronous")).scalar()),
        "cache_size": str(session.execute(text("PRAGMA cache_size")).scalar()),
    }
    # We don't change journal_mode anymore — leaving WAL active is what
    # lets the parallel `/progress` polls run without blocking the
    # writer. We *do* still need to be outside any active transaction
    # to set PRAGMAs reliably on SQLite, so issue a rollback first.
    session.rollback()
    session.execute(text("PRAGMA synchronous = OFF"))
    # 64 MB page cache. Default is ~2 MB which is starvingly small for
    # a 240k-row table-snapshot batch. With 64 MB SQLite can keep the
    # B-tree fanout pages hot across batches.
    session.execute(text("PRAGMA cache_size = -65536"))
    return previous


def _restore_pragmas(session: Session, previous: Dict[str, str]) -> None:
    """Best-effort PRAGMA restore. Never raises — diagnostic-only."""
    try:
        session.rollback()
        session.execute(text(f"PRAGMA synchronous = {previous['synchronous']}"))
        session.execute(text(f"PRAGMA cache_size = {previous['cache_size']}"))
    except Exception as exc:
        logger.warning("[ingest] failed to restore PRAGMAs: %s", exc)


def _content_type_to_category(ct: ContentType) -> Optional[str]:
    """Translate the enum into the persister's category bucket name.

    Returns None for content types this endpoint doesn't accept (e.g.
    parser JSON), letting the caller raise a clean 400 instead of
    routing it to the wrong pipeline.

    PDCR usage files are valid here as of PR-D (Pipeline 3). They are
    routed to the PDCR persisters after the dict pipeline finishes —
    see ``_DICT_CATEGORIES`` / ``_PDCR_CATEGORIES`` for the partitions.
    """
    return {
        ContentType.DICT_DATABASES: "databases",
        ContentType.DICT_TABLES: "tables",
        ContentType.DICT_COLUMNS: "columns",
        ContentType.DICT_INDICES: "indices",
        ContentType.DICT_PARTITIONING: "partitioning",
        ContentType.DICT_TABLETEXT: "tabletext",
        ContentType.USAGE_DBQL: "dbql_log",
        ContentType.USAGE_OBJECT: "object_usage",
    }.get(ct)


# Partition tables used by the handler to route each detected file
# into the right pipeline. Keeping them as module-level constants
# (rather than literals in the handler body) means a future reviewer
# spotting "is X dict or PDCR?" has a single place to look.
_DICT_CATEGORIES = {
    "databases", "tables", "columns",
    "indices", "partitioning", "tabletext",
}
_PDCR_CATEGORIES = {"dbql_log", "object_usage"}

# DBQL (pdcr_log) ingestion switch. Disabled by decision (Rahul,
# 2026-06-02): SCION stores the reassembled SQL text per QueryID but
# nothing consumes it, and DataDNA isn't joining against it near-term,
# so we keep the database lean and don't persist it. The reader and the
# `dbql_query` table/migration stay in place (dormant) — flip this to
# True to re-enable if DataDNA later wants the QueryID → SQL correlation.
INGEST_DBQL = False


# ──── The endpoint ────

@router.get("/{import_id}/progress")
def get_import_progress(import_id: str) -> dict:
    """Return live state of an in-flight import.

    Polled by the frontend while the parallel POST is hung on the
    long persist phase. Returns 404 if the `import_id` isn't
    registered (either it never started, or it finished and was
    evicted from the in-memory cache).
    """
    state = import_progress.get(import_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No active import with that id. Either it hasn't started yet, "
                "or it finished and the progress entry has been evicted."
            ),
        )
    return state.to_dict()


@router.post("/{import_id}/cancel")
def cancel_import(import_id: str) -> dict:
    """Request cooperative cancellation of an in-flight import.

    Sets the `cancel_requested` flag on the in-memory progress
    record. The handler polls this flag at checkpoints (between
    bulk-insert batches) and raises `ImportCancelled` when it sees
    it set, which triggers a rollback of the in-flight transaction
    so the partial snapshot never lands.

    Returns 200 with `{cancelled: true}` if the flag was set; 404 if
    the import isn't registered or has already finished. The latter
    case is intentionally not an error — the cancel button can race
    with natural completion and we don't want to surface that as a
    user-visible failure.
    """
    flagged = import_progress.request_cancel(import_id)
    if not flagged:
        # Either unknown id or already finished. Both are OK from
        # the user's perspective ("nothing to cancel"), but we
        # return 404 so callers can distinguish from a real cancel.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No active import with that id, or it already finished. "
                "Nothing to cancel."
            ),
        )
    return {"import_id": import_id, "cancelled": True}


@router.post("", response_model=DictImportResponse)
def import_dict_batch(
    files: List[UploadFile] = File(
        ...,
        description=(
            "Up to 8 extract files in any combination — the 6 dict views "
            "(databases, tables, columns, indices, partitioning, "
            "tabletext) plus the 2 PDCR usage extracts "
            "(pdcr_log_*, pdcr_object_usage_*). The endpoint auto-detects "
            "which view each file represents by content; filenames matching "
            "Rahul's templates are detected with high confidence. PDCR "
            "files are routed to the usage persisters after the dict "
            "snapshot commits — see Pipeline 3 in docs/SPEC.md."
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
    import_id: Optional[str] = Form(
        None,
        description=(
            "Optional client-generated identifier (UUID) the frontend "
            "uses to poll progress while the POST is in flight. When "
            "omitted, the import still runs but no progress tracking "
            "is registered."
        ),
    ),
    finalize_progress: bool = True,
) -> DictImportResponse:
    """Accept up to 6 dict files in one request and persist as a snapshot.

    The batch must internally reference the same extraction run
    (`source_system_name` + `extract_run_id`). Files can arrive in
    any order; we route by content-type detection, not multipart
    field position.

    Why this is `def` (not `async def`): the heavy phases (parse,
    persist, post-ingest) are all synchronous and add up to several
    minutes on a real customer extract. If we ran inside the asyncio
    event loop, those sync calls would block the loop and starve
    every other request — including the parallel `/progress` polls
    and the `/cancel` POST that the frontend relies on for live
    feedback. Making the handler sync delegates it to FastAPI's
    threadpool (default 40 workers via anyio), keeping the loop free
    to dispatch the small endpoints concurrently. We pay nothing for
    the change because there's no async I/O here anyway —
    `upload.file.read()` is the sync equivalent of
    `await upload.read()`, SQLAlchemy is synchronous, and the
    downstream parsers / persisters are all sync.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded. Send at least one dict extract file.",
        )

    # Stage timings collected as we go. We log each stage individually
    # at INFO and then emit a single summary table at the end. Keys are
    # ordered semantically (the same order the user perceives the
    # work happening) — the dict preserves insertion order in 3.7+.
    timings: Dict[str, float] = {}
    sizes_by_category: Dict[str, int] = {}
    t_overall = time.perf_counter()
    logger.info("[ingest] ───────────── dict-import started — %d file(s) ─────────────", len(files))

    # Register progress tracking if the client supplied an import_id.
    # Every subsequent step pushes updates via `import_progress`; the
    # frontend polls `GET /{import_id}/progress` in parallel to render
    # the checklist UI. Wrapped in a helper so the rest of the handler
    # stays readable — `_progress_*` no-ops cleanly when import_id is
    # None (i.e. for non-UI callers like our pytest TestClient).
    if import_id is not None:
        import_progress.init(import_id, import_progress.DICT_IMPORT_STEPS)

    def _progress_start(step: str, caption: Optional[str] = None) -> None:
        if import_id is not None:
            import_progress.start_step(import_id, step, caption)

    def _progress_update(
        step: str,
        progress: Optional[float] = None,
        caption: Optional[str] = None,
    ) -> None:
        if import_id is not None:
            import_progress.update_progress(import_id, step, progress, caption)

    def _progress_end(step: str, caption: Optional[str] = None) -> None:
        if import_id is not None:
            import_progress.end_step(import_id, step, caption)

    # ──── Step 1: stream every upload to disk + classify by content ────
    # Paths are kept by category so multiple files of the same view
    # would overwrite each other deliberately (only one
    # `columnsv_*.dat` per batch is the contract). The temp files are
    # cleaned up in the `finally` at the end of the handler.
    temp_paths: List[Path] = []
    paths_by_category: Dict[str, Path] = {}
    filenames_by_category: Dict[str, str] = {}
    # PDCR routing (PR-D): separate buckets so the dict pipeline never
    # sees `pdcr_log_*` / `pdcr_object_usage_*` files. They run after
    # the dict snapshot commits (or alone, if the batch is PDCR-only).
    pdcr_paths_by_category: Dict[str, Path] = {}
    pdcr_filenames_by_category: Dict[str, str] = {}

    try:
        t_upload = time.perf_counter()
        _progress_start("upload", caption=f"0 / {len(files)} files")
        total_uploaded_bytes = 0
        for idx, upload in enumerate(files):
            t_one = time.perf_counter()
            tmp_path = _stream_upload_to_disk(upload)
            size = tmp_path.stat().st_size
            total_uploaded_bytes += size
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

            if category in _PDCR_CATEGORIES:
                pdcr_paths_by_category[category] = tmp_path
                pdcr_filenames_by_category[category] = upload.filename or category
            else:
                paths_by_category[category] = tmp_path
                filenames_by_category[category] = upload.filename or category
            sizes_by_category[category] = size
            logger.info(
                "[ingest] uploaded %-13s %10s in %s  (%s)",
                category, _fmt_bytes(size),
                _fmt_time(time.perf_counter() - t_one),
                upload.filename or "?",
            )
            _progress_update(
                "upload",
                progress=(idx + 1) / max(len(files), 1),
                caption=f"{idx + 1} / {len(files)} files · {_fmt_bytes(total_uploaded_bytes)}",
            )
        timings["1_upload"] = time.perf_counter() - t_upload
        _progress_end(
            "upload",
            caption=f"{len(files)} files · {_fmt_bytes(total_uploaded_bytes)}",
        )

        # ──── PDCR-only batch guard ────
        # PR-D scope is mixed batches (dict + PDCR) and dict-only.
        # PDCR-only batches need a snapshot to resolve identifiers
        # against; supporting them properly is deferred to a later
        # PR. Surface a clean 400 here rather than letting the
        # validator raise its less-helpful "empty batch" error.
        if not paths_by_category and pdcr_paths_by_category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "PDCR-only batches aren't supported yet. Upload the "
                    "PDCR files (pdcr_log_*, pdcr_object_usage_*) "
                    "together with the 6 dict extracts they belong to."
                ),
            )

        # ──── Step 2: parse the small views eagerly (fits in memory) ────
        # databases ≤ 50k rows, tables ≤ 500k, partitioning ≤ 50k —
        # well under any memory pressure. tabletext can hit hundreds of
        # MB for a large EDW but its 9-field ENDREC layout doesn't
        # have a streaming reader yet (see tabletext TODO in reader);
        # in practice it's still small relative to columns.
        t_parse_small = time.perf_counter()
        _progress_start("parse_files", caption="reading files…")
        try:
            t_phase = time.perf_counter()
            databases = (
                dict_flat_file_reader.read_databases(paths_by_category["databases"])
                if "databases" in paths_by_category else []
            )
            logger.info("[ingest] parsed databases    %9d rows in %s",
                        len(databases), _fmt_time(time.perf_counter() - t_phase))
            _progress_update("parse_files", caption=f"{len(databases):,} databases parsed")

            t_phase = time.perf_counter()
            tables = (
                dict_flat_file_reader.read_tables(paths_by_category["tables"])
                if "tables" in paths_by_category else []
            )
            logger.info("[ingest] parsed tables       %9d rows in %s",
                        len(tables), _fmt_time(time.perf_counter() - t_phase))
            _progress_update("parse_files", caption=f"{len(tables):,} tables parsed")

            t_phase = time.perf_counter()
            partitioning = (
                dict_flat_file_reader.read_partitioning(
                    paths_by_category["partitioning"]
                )
                if "partitioning" in paths_by_category else []
            )
            logger.info("[ingest] parsed partitioning %9d rows in %s",
                        len(partitioning), _fmt_time(time.perf_counter() - t_phase))
            _progress_update("parse_files", caption=f"{len(partitioning):,} partitioning rows parsed")

            t_phase = time.perf_counter()
            tabletext = (
                dict_flat_file_reader.read_tabletext(paths_by_category["tabletext"])
                if "tabletext" in paths_by_category else []
            )
            logger.info("[ingest] parsed tabletext    %9d rows in %s",
                        len(tabletext), _fmt_time(time.perf_counter() - t_phase))
        except dict_flat_file_reader.DictFlatFileError as e:
            if import_id is not None:
                import_progress.mark_finished(
                    import_id, ok=False, error_message=f"Parse error: {e}",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Parse error: {e}",
            )
        timings["2_parse_small_files"] = time.perf_counter() - t_parse_small
        _progress_end(
            "parse_files",
            caption=(
                f"{len(databases):,} databases · {len(tables):,} tables · "
                f"{len(partitioning):,} partitioning · {len(tabletext):,} ddl fragments"
            ),
        )

        # ──── Step 3: identity validation ────
        t_validate = time.perf_counter()
        _progress_start("validate_identity", caption="checking source / run_id consistency…")
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
            if import_id is not None:
                import_progress.mark_finished(
                    import_id, ok=False, error_message=str(e),
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        timings["3_validate_identity"] = time.perf_counter() - t_validate
        logger.info("[ingest] identity validation passed in %s — %s",
                    _fmt_time(timings["3_validate_identity"]),
                    identity.snapshot_label)
        _progress_end(
            "validate_identity",
            caption=identity.snapshot_label,
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

        t_persist = time.perf_counter()
        _progress_start("persist_data", caption="writing rows to database…")
        with Session(bind=engine) as session:
            # Switch SQLite into fast-bulk-insert mode for this session.
            # See `_apply_bulk_insert_pragmas` docstring for the full
            # rationale and trade-off. We always restore in `finally`
            # so a failed import doesn't leave the connection (or the
            # connection-pool, if SQLite ever returns one) with relaxed
            # durability bleed-through to subsequent requests.
            previous_pragmas = _apply_bulk_insert_pragmas(session)
            logger.info(
                "[ingest] SQLite tuned for bulk insert: "
                "synchronous=OFF, cache_size=64MB (journal_mode=WAL kept from engine)"
            )
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
                    import_id=import_id,
                )
                t_commit = time.perf_counter()
                _progress_update("persist_data", caption="committing transaction…")
                session.commit()
                logger.info("[ingest] session.commit() took %s",
                            _fmt_time(time.perf_counter() - t_commit))
            except import_progress.ImportCancelled as e:
                # Cooperative cancellation requested by the client.
                # Roll back the partial transaction, mark the import
                # as terminated with status=cancelled, and surface a
                # clean 499 (the de-facto "client closed request"
                # status code; FastAPI doesn't define it, so we use
                # 499 as a custom integer). The frontend treats it as
                # "the cancel went through" — not an error to toast.
                session.rollback()
                if import_id is not None:
                    state = import_progress.get(import_id)
                    if state is not None:
                        state.status = "cancelled"
                        state.ended_at = time.perf_counter()
                        state.error_message = str(e)
                logger.info("[ingest] cancelled by client (%s)", e)
                raise HTTPException(
                    status_code=499,
                    detail=str(e),
                )
            except dict_flat_file_reader.DictFlatFileError as e:
                # Mid-stream parse error from the generators surfaces
                # as a clean 400 rather than a 500.
                session.rollback()
                if import_id is not None:
                    import_progress.mark_finished(
                        import_id, ok=False,
                        error_message=f"Parse error during persist: {e}",
                    )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Parse error during persist: {e}",
                )
            except Exception as e:
                session.rollback()
                if import_id is not None:
                    import_progress.mark_finished(
                        import_id, ok=False,
                        error_message=f"Failed to persist snapshot: {e}",
                    )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to persist snapshot: {e}",
                )
            finally:
                # Restore the durability settings before this session's
                # connection goes back to the pool. Without this, a
                # later request handler could pick up a connection
                # still running with `synchronous = OFF`.
                _restore_pragmas(session, previous_pragmas)

        timings["4_persist_total"] = time.perf_counter() - t_persist
        _progress_end(
            "persist_data",
            caption=(
                f"{result.tables_created:,} tables · "
                f"{result.columns_created:,} columns · "
                f"{result.indices_created:,} index rows"
            ),
        )
        logger.info("[ingest] persist (parse+stream columns/indices + bulk insert + commit) %s",
                    _fmt_time(timings["4_persist_total"]))

        # ──── Step 5: post-ingest analytical pipeline ────
        # Skipped on idempotent re-imports — the prior run already
        # populated everything, re-running would be wasted work.
        if not result.skipped_existing:
            t_post = time.perf_counter()
            _progress_start(
                "post_ingest",
                caption="hashing structure, building graph, computing criticality…",
            )
            dict_persister.run_post_ingest_pipeline(
                result.snapshot_id, import_id=import_id,
            )
            timings["5_post_ingest"] = time.perf_counter() - t_post
            logger.info("[ingest] post-ingest pipeline %s",
                        _fmt_time(timings["5_post_ingest"]))
            _progress_end("post_ingest", caption="all derived tables populated")
        else:
            # Idempotent re-import — mark post-ingest as a no-op rather
            # than leaving it in "pending" forever, otherwise the UI
            # checklist would show one step stuck on the spinner.
            _progress_end("post_ingest", caption="skipped (snapshot already exists)")

        # ──── Step 6: PDCR usage ingest (Pipeline 3, PR-D) ────
        # Runs in its own session so a failure here doesn't roll back
        # the dict snapshot that already committed. The persisters
        # use natural-key idempotency, so a retry of just the PDCR
        # half is safe.
        dbql_result = pdcr_persister.PDCRPersistResult()
        obj_result = pdcr_persister.PDCRPersistResult()
        pdcr_snapshot_id: Optional[int] = None
        criticality_recomputed = False
        criticality_high = 0
        criticality_medium = 0
        criticality_low = 0

        if pdcr_paths_by_category:
            t_pdcr = time.perf_counter()
            _progress_start(
                "persist_pdcr",
                caption=f"{len(pdcr_paths_by_category)} PDCR file(s)…",
            )
            # The just-created dict snapshot is the resolution target.
            # `result.snapshot_id` is populated even on idempotent
            # re-imports (the persister returns the matching existing
            # snapshot_id rather than creating a new one).
            pdcr_snapshot_id = result.snapshot_id
            with Session(bind=engine) as pdcr_session:
                try:
                    if "dbql_log" in pdcr_paths_by_category and INGEST_DBQL:
                        dbql_records = pdcr_flat_file_reader.read_dbql_log(
                            pdcr_paths_by_category["dbql_log"]
                        )
                        dbql_result = pdcr_persister.persist_dbql_log(
                            dbql_records, pdcr_session,
                        )
                    if "object_usage" in pdcr_paths_by_category:
                        obj_records = pdcr_flat_file_reader.read_object_usage(
                            pdcr_paths_by_category["object_usage"]
                        )
                        obj_result = pdcr_persister.persist_object_usage(
                            obj_records, pdcr_session,
                            snapshot_id=pdcr_snapshot_id,
                        )
                    pdcr_session.commit()
                except pdcr_flat_file_reader.PDCRFlatFileError as e:
                    pdcr_session.rollback()
                    if import_id is not None:
                        import_progress.mark_finished(
                            import_id, ok=False,
                            error_message=f"PDCR parse error: {e}",
                        )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"PDCR parse error: {e}",
                    )
                except Exception as e:
                    pdcr_session.rollback()
                    if import_id is not None:
                        import_progress.mark_finished(
                            import_id, ok=False,
                            error_message=f"Failed to persist PDCR data: {e}",
                        )
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to persist PDCR data: {e}",
                    )
            timings["6_persist_pdcr"] = time.perf_counter() - t_pdcr
            logger.info(
                "[ingest] PDCR persisted in %s — "
                "dbql inserted=%d dup=%d invalid=%d · "
                "object_usage inserted=%d unmapped=%d orphan=%d invalid=%d",
                _fmt_time(timings["6_persist_pdcr"]),
                dbql_result.inserted, dbql_result.skipped_duplicate,
                dbql_result.skipped_invalid,
                obj_result.inserted, obj_result.skipped_unmapped_type,
                obj_result.skipped_orphan, obj_result.skipped_invalid,
            )

            # ──── Step 6b: criticality re-compute with usage (PR-E) ────
            # The post-ingest pipeline ran ``compute_criticality`` with
            # ``usage_available=False`` because no UsageEvent rows
            # existed for this snapshot yet. Now that PR-D persisted
            # them, re-run the engine with ``usage_available=True`` so
            # the criticality cache reflects real query / access
            # counts. ``force=True`` is mandatory because the post-
            # ingest pass already populated rows for this snapshot —
            # without it, the cache-check at the top of
            # ``compute_criticality`` would return early.
            #
            # Gate on ``obj_result.inserted > 0`` so we don't pay the
            # full re-compute when the batch only carried DBQL (which
            # doesn't feed UsageEvent — see persister docstrings).
            if obj_result.inserted > 0:
                _progress_update(
                    "persist_pdcr",
                    caption="recomputing criticality with usage data…",
                )
                t_crit = time.perf_counter()
                try:
                    crit_rows = compute_criticality(
                        pdcr_snapshot_id, force=True, usage_available=True,
                    )
                    criticality_recomputed = True
                    for r in crit_rows:
                        lvl = r["criticality_level"]
                        if lvl == "HIGH":
                            criticality_high += 1
                        elif lvl == "MEDIUM":
                            criticality_medium += 1
                        else:
                            criticality_low += 1
                    timings["6b_recompute_criticality"] = (
                        time.perf_counter() - t_crit
                    )
                    logger.info(
                        "[ingest] criticality re-computed with usage in %s — "
                        "HIGH=%d MEDIUM=%d LOW=%d (total=%d)",
                        _fmt_time(timings["6b_recompute_criticality"]),
                        criticality_high, criticality_medium,
                        criticality_low, len(crit_rows),
                    )
                except Exception as e:
                    # Don't fail the whole import over a criticality
                    # re-compute glitch — the dict snapshot + PDCR
                    # rows are already committed, and the on-demand
                    # /usage/criticality endpoint will recompute on
                    # next request. Log and continue.
                    logger.warning(
                        "[ingest] criticality re-compute failed for %s: %s",
                        pdcr_snapshot_id, e,
                    )

            # Surface DBQL explicitly rather than silently dropping it
            # (FR-13): if a pdcr_log file was uploaded but ingestion is
            # disabled, say so instead of reporting "0 queries".
            dbql_caption = (
                f"{dbql_result.inserted:,} queries"
                if INGEST_DBQL
                else "DBQL skipped (storage disabled)"
                if "dbql_log" in pdcr_paths_by_category
                else "no DBQL"
            )
            _progress_end(
                "persist_pdcr",
                caption=(
                    f"{dbql_caption} · {obj_result.inserted:,} usage rows"
                    + (
                        f" · criticality HIGH={criticality_high:,}"
                        if criticality_recomputed else ""
                    )
                ),
            )
        else:
            # No PDCR files in this batch — mark the step as a no-op
            # so the UI checklist doesn't sit on a spinner forever.
            _progress_end(
                "persist_pdcr",
                caption="skipped (no PDCR files in batch)",
            )

        if import_id is not None and finalize_progress:
            import_progress.mark_finished(import_id, ok=True)

        # Final summary table — easy to grep for and to copy/paste
        # when comparing two runs to see where time went.
        total = time.perf_counter() - t_overall
        logger.info("[ingest] ───────────── summary ─────────────")
        logger.info("[ingest]   snapshot_id=%s  source=%s  run=%s",
                    result.snapshot_id, identity.source_system_name,
                    identity.extract_run_id[:24] + ("…" if len(identity.extract_run_id) > 24 else ""))
        logger.info("[ingest]   persisted: schemas=%d tables=%d columns=%d indices=%d partitioning=%d ddl=%d",
                    result.schemas_created, result.tables_created,
                    result.columns_created, result.indices_created,
                    result.partitioning_created, result.ddl_text_created)
        for stage, elapsed in timings.items():
            pct = (elapsed / total * 100) if total > 0 else 0
            logger.info("[ingest]   %-25s %12s  (%4.1f%%)", stage, _fmt_time(elapsed), pct)
        logger.info("[ingest]   %-25s %12s", "TOTAL", _fmt_time(total))
        logger.info("[ingest] ────────────────────────────────────")

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
            dbql_inserted=dbql_result.inserted,
            dbql_skipped_duplicate=dbql_result.skipped_duplicate,
            dbql_skipped_invalid=dbql_result.skipped_invalid,
            object_usage_inserted=obj_result.inserted,
            object_usage_skipped_unmapped_type=obj_result.skipped_unmapped_type,
            object_usage_skipped_orphan=obj_result.skipped_orphan,
            object_usage_skipped_invalid=obj_result.skipped_invalid,
            object_usage_skipped_by_type=dict(obj_result.skipped_by_type),
            pdcr_resolved_against_snapshot_id=pdcr_snapshot_id,
            criticality_recomputed=criticality_recomputed,
            criticality_high_count=criticality_high,
            criticality_medium_count=criticality_medium,
            criticality_low_count=criticality_low,
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
