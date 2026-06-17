from __future__ import annotations

"""Server-side import from the mounted share (no file upload required).

Scans SCION_SHARE_MOUNT_PATH for dict .dat files, PDCR .dat files, and
the lineage-mvp.json, then ingests them in the correct order:

  1. Dict + PDCR .dat files  →  new snapshot  (via dict_import pipeline)
  2. Lineage JSON            →  attached to that snapshot  (parser_import)

The endpoint reads from the filesystem on the server — the browser never
needs to upload any file. This is the counterpart to the notification bell
that shows "New data available from share."
"""

import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from starlette.datastructures import UploadFile

from app.config import SCION_SHARE_MOUNT_PATH
from app.api.v1 import import_progress
from app.api.v1.dict_import import DictImportResponse, import_dict_batch
from app.parser_ingest import ingestor, noise_filter, teradata_parser

router = APIRouter(prefix="/share-import", tags=["share-import"])

# Sub-directory names inside the share that we scan.
_DICT_DIR = "Data Dictionary"
_LINEAGE_DIR = "Data Lineage"
_PDCR_DIR = "Object Usage"


class ShareImportResponse(BaseModel):
    snapshot_id: int
    dict_result: DictImportResponse
    lineage_attached: bool
    lineage_tables: int
    lineage_edges: int
    lineage_columns: int
    lineage_warnings: List[str]


class ShareScanResponse(BaseModel):
    """Non-destructive preview of what the share contains."""
    share_available: bool
    share_path: str
    dict_files: List[str]
    pdcr_files: List[str]
    lineage_files: List[str]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _iter_share_files(subdir: str, mount_path: str = SCION_SHARE_MOUNT_PATH) -> List[Path]:
    """Return all regular files in <mount_path>/<subdir>."""
    base = Path(mount_path) / subdir
    if not base.is_dir():
        return []
    return [f for f in base.iterdir() if f.is_file()]


def _path_to_upload(path: Path) -> UploadFile:
    """Wrap a server-side file as a Starlette UploadFile.

    The file is opened in binary mode; import_dict_batch's streaming
    helper reads it in 4-MiB chunks via upload.file.read() — the same
    way it handles real HTTP multipart uploads.
    """
    fobj = open(path, "rb")  # noqa: SIM115  — kept open for the handler's lifetime
    return UploadFile(filename=path.name, file=fobj)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/scan", response_model=ShareScanResponse)
def scan_share(
    path: Optional[str] = None,
) -> ShareScanResponse:
    """Return the list of importable files found in the share (no-op).

    `path` overrides the server-default SCION_SHARE_MOUNT_PATH for this
    request — useful when the share is mounted at a different location.
    """
    mount = path or SCION_SHARE_MOUNT_PATH
    base = Path(mount)
    if not base.exists():
        return ShareScanResponse(
            share_available=False,
            share_path=mount,
            dict_files=[], pdcr_files=[], lineage_files=[],
        )
    return ShareScanResponse(
        share_available=True,
        share_path=mount,
        dict_files=[f.name for f in _iter_share_files(_DICT_DIR, mount)],
        pdcr_files=[f.name for f in _iter_share_files(_PDCR_DIR, mount)],
        lineage_files=[f.name for f in _iter_share_files(_LINEAGE_DIR, mount)],
    )


@router.post("", response_model=ShareImportResponse)
def import_from_share(
    force: bool = False,
    path: Optional[str] = None,
    import_id: Optional[str] = None,
) -> ShareImportResponse:
    """Import all files from the share in one unified snapshot.

    Dict + PDCR .dat files land first (creating a single snapshot);
    then the lineage JSON is attached to that same snapshot via the
    parser pipeline. The result is one snapshot that contains dict
    structure, usage data, AND DBQL lineage.

    `path` overrides the server-default SCION_SHARE_MOUNT_PATH so the
    user can point to a different folder without restarting the server.
    """
    mount = path or SCION_SHARE_MOUNT_PATH
    base = Path(mount)
    if not base.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Share path not accessible: {mount}. "
                "Check that the path exists and is readable on the server."
            ),
        )

    dict_paths = _iter_share_files(_DICT_DIR, mount)
    pdcr_paths = _iter_share_files(_PDCR_DIR, mount)
    lineage_paths = _iter_share_files(_LINEAGE_DIR, mount)

    if not dict_paths:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"No dict files found in {SCION_SHARE_MOUNT_PATH}/{_DICT_DIR}. "
                "At least one dict extract is required."
            ),
        )

    # ──── 1. Import dict + PDCR files ────
    # Build UploadFile wrappers so we can reuse the existing handler.
    # Opened files are tracked for cleanup in the finally block.
    upload_files: List[UploadFile] = []
    open_handles = []
    try:
        for path in dict_paths + pdcr_paths:
            fobj = open(path, "rb")
            open_handles.append(fobj)
            upload_files.append(UploadFile(filename=path.name, file=fobj))  # type: ignore[arg-type]

        # Call the existing dict-import handler directly. It handles
        # detection, validation, streaming to temp, persisting, and
        # criticality re-compute. When the UI supplies import_id, the
        # normal dict-import progress screen can follow this share-side
        # import too.
        dict_result: DictImportResponse = import_dict_batch(
            files=upload_files,
            force=force,
            import_id=import_id,
            finalize_progress=False,
        )
    finally:
        for fobj in open_handles:
            try:
                fobj.close()
            except Exception:
                pass

    snapshot_id: int = dict_result.snapshot_id

    # ──── 2. Attach lineage JSON to the same snapshot ────
    lineage_attached = False
    lineage_tables = 0
    lineage_edges = 0
    lineage_columns = 0
    lineage_warnings: List[str] = []

    json_files = [p for p in lineage_paths if p.suffix.lower() == ".json"]
    if json_files:
        lineage_file = json_files[0]
        try:
            if import_id is not None:
                import_progress.start_step(
                    import_id,
                    "persist_pdcr",
                    caption=f"attaching lineage from {lineage_file.name}...",
                )
            payload_raw = json.loads(lineage_file.read_text(encoding="utf-8"))
            parsed = teradata_parser.parse(payload_raw)
            noise_filter.apply(parsed)
            report = ingestor.ingest(
                parsed,
                description=f"Lineage from share ({lineage_file.name})",
                attach_to_snapshot_id=snapshot_id,
            )
            lineage_attached = True
            lineage_tables = report.persisted_counts.get("tables", 0)
            lineage_edges = report.persisted_counts.get("graph_edges", 0)
            lineage_columns = report.persisted_counts.get("columns", 0)
            lineage_warnings = report.warnings
            if import_id is not None:
                import_progress.end_step(
                    import_id,
                    "persist_pdcr",
                    caption=(
                        f"lineage attached: {lineage_tables:,} tables, "
                        f"{lineage_edges:,} edges"
                    ),
                )
        except teradata_parser.ParserPayloadError as exc:
            lineage_warnings.append(f"Lineage parse error: {exc}")
            if import_id is not None:
                import_progress.end_step(
                    import_id,
                    "persist_pdcr",
                    caption=f"lineage parse warning: {exc}",
                )
        except Exception as exc:
            lineage_warnings.append(f"Lineage import error: {exc}")
            if import_id is not None:
                import_progress.end_step(
                    import_id,
                    "persist_pdcr",
                    caption=f"lineage import warning: {exc}",
                )

    if import_id is not None:
        import_progress.mark_finished(import_id, ok=True)

    return ShareImportResponse(
        snapshot_id=snapshot_id,
        dict_result=dict_result,
        lineage_attached=lineage_attached,
        lineage_tables=lineage_tables,
        lineage_edges=lineage_edges,
        lineage_columns=lineage_columns,
        lineage_warnings=lineage_warnings,
    )
