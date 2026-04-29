from __future__ import annotations

"""Format + content-type detection for SCION ingest uploads.

Goal: a single user-facing endpoint that accepts whatever Rahul produces
(today: parser JSON + dict `.dat`; tomorrow: maybe parser `.dat` and
dict JSON — see Meeting #8 follow-up). The endpoint detects format from
content (not extension) and routes to the right pipeline.

Why content-based detection
- Filenames lie. `.dat` is just convention; `.json` could be renamed.
- Customers will rename files. They always do.
- The first non-whitespace byte is enough to tell JSON from flat-file:
  JSON starts with `{` or `[`; flat-file starts with the source_system
  literal followed by `§`.

This module is **pure**: takes bytes (or the head of bytes) in, returns
a typed verdict. No I/O, no DB. Caller owns the file.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Format(str, Enum):
    """Wire format of a single file."""
    JSON = "json"
    FLAT_FILE = "flat_file"   # §-delimited / ENDREC-terminated
    UNKNOWN = "unknown"


class ContentType(str, Enum):
    """Logical pipeline the file belongs to.

    Today the mapping is:
      - PARSER_LINEAGE  ← `lineage-mvp.json` style (parser pipeline)
      - DICT_DATABASES, DICT_TABLES, DICT_COLUMNS, DICT_INDICES,
        DICT_PARTITIONING, DICT_TABLETEXT  ← Rahul's data dictionary
        flat-file extracts (six-file batch)

    Both pipelines could in theory swap formats in the future; that's
    why detection is two-step (format → content-type) instead of one.
    """
    PARSER_LINEAGE = "parser_lineage"
    DICT_DATABASES = "dict_databases"
    DICT_TABLES = "dict_tables"
    DICT_COLUMNS = "dict_columns"
    DICT_INDICES = "dict_indices"
    DICT_PARTITIONING = "dict_partitioning"
    DICT_TABLETEXT = "dict_tabletext"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DetectionResult:
    """Outcome of inspecting a single file."""
    format: Format
    content_type: ContentType
    confidence: str          # "high" | "medium" | "low"
    reason: str              # human-readable why-we-think-this


# ──── Filename hints (used as a tiebreaker, never as the primary signal) ──
# These prefixes mirror Rahul's `_export.sql` template names. The
# detector still inspects the bytes — these only kick in when the
# byte-level check finds "flat-file" but can't choose which view.
_DICT_FILENAME_PREFIXES = {
    "databasesv_": ContentType.DICT_DATABASES,
    "tablesv_":    ContentType.DICT_TABLES,
    "columnsv_":   ContentType.DICT_COLUMNS,
    "indicesv_":   ContentType.DICT_INDICES,
    "partitioningconstraintsv_": ContentType.DICT_PARTITIONING,
    "tabletextv_": ContentType.DICT_TABLETEXT,
}


def detect(content: bytes, filename: Optional[str] = None) -> DetectionResult:
    """Detect format + content-type of a single file.

    Args:
        content: raw file bytes (or at least the first ~8 KB).
        filename: optional, used only as a tiebreaker.

    The function never raises — UNKNOWN is a valid verdict, and the
    caller decides how to react (reject, log, queue for review).
    """
    fmt = _detect_format(content)
    if fmt is Format.JSON:
        return _detect_json_content(content, filename)
    if fmt is Format.FLAT_FILE:
        return _detect_flat_file_content(content, filename)
    return DetectionResult(
        format=Format.UNKNOWN,
        content_type=ContentType.UNKNOWN,
        confidence="low",
        reason="File starts with neither JSON nor a recognised flat-file marker.",
    )


# ──── Format-level detection ────

def _detect_format(content: bytes) -> Format:
    """First byte is enough. Skip whitespace + UTF-8 BOM.

    JSON: first non-whitespace byte is `{` or `[`.
    Flat-file: first non-whitespace bytes contain the `§` field
    delimiter (encoded as `\\xc2\\xa7` in UTF-8) within the first KB.
    """
    head = content[:8192].lstrip(b"\xef\xbb\xbf").lstrip(b" \t\r\n")
    if not head:
        return Format.UNKNOWN
    if head[:1] in (b"{", b"["):
        return Format.JSON
    # § = U+00A7, UTF-8 = 0xC2 0xA7. The flat-file always starts with the
    # source_system_name (a literal like "Transcend-DevTest") followed by
    # the delimiter, so we look for the delimiter byte sequence early.
    if b"\xc2\xa7" in head[:1024]:
        return Format.FLAT_FILE
    return Format.UNKNOWN


# ──── JSON content-type detection ────

def _detect_json_content(
    content: bytes,
    filename: Optional[str],
) -> DetectionResult:
    """Look at JSON top-level shape to classify pipeline.

    The parser's lineage JSON has a recognisable shape (top-level
    `objects` / `lineage` / `tables` keys). We check for the lineage
    fingerprint first because it's the only JSON we accept today.

    A future "dict in JSON" payload would land here too — we'd add a
    branch when Rahul confirms the format.
    """
    head = content[:4096]
    # Cheap byte-level scan — full JSON parse is expensive on multi-MB
    # uploads and overkill for shape detection. We rely on the fact
    # that the top-level keys appear early in any reasonable export.
    if b'"objects"' in head or b'"lineage"' in head:
        return DetectionResult(
            format=Format.JSON,
            content_type=ContentType.PARSER_LINEAGE,
            confidence="high",
            reason="JSON with `objects`/`lineage` top-level keys (parser pipeline).",
        )
    return DetectionResult(
        format=Format.JSON,
        content_type=ContentType.UNKNOWN,
        confidence="low",
        reason="JSON file but doesn't match any known SCION schema.",
    )


# ──── Flat-file content-type detection ────

def _detect_flat_file_content(
    content: bytes,
    filename: Optional[str],
) -> DetectionResult:
    """Identify which of the 6 dict views this flat-file represents.

    Strategy:
      1. Filename prefix (`tablesv_`, `columnsv_`, ...) is the most
         reliable signal — Rahul's templates produce predictable names.
      2. Fallback: count fields in the first record. 16 fields → one
         of the 5 standard views (we still need filename to disambiguate);
         9 fields → tabletext.
    """
    # Try filename first.
    if filename:
        name = filename.lower()
        for prefix, ct in _DICT_FILENAME_PREFIXES.items():
            if name.startswith(prefix):
                return DetectionResult(
                    format=Format.FLAT_FILE,
                    content_type=ct,
                    confidence="high",
                    reason=f"Filename starts with `{prefix}` — matches dict view.",
                )

    # Fallback: count fields in first record.
    try:
        head_str = content[:4096].decode("utf-8", errors="replace")
    except Exception:
        head_str = ""
    first_line = head_str.split("\n", 1)[0]
    field_count = first_line.count("§") + 1
    if field_count == 9:
        return DetectionResult(
            format=Format.FLAT_FILE,
            content_type=ContentType.DICT_TABLETEXT,
            confidence="medium",
            reason=f"Flat-file with {field_count} fields per record — tabletext layout.",
        )
    if field_count == 16:
        # Can't disambiguate without a filename. Caller has to decide.
        return DetectionResult(
            format=Format.FLAT_FILE,
            content_type=ContentType.UNKNOWN,
            confidence="low",
            reason=(
                "16-field flat-file (one of databases/tables/columns/"
                "indices/partitioning) but no filename to disambiguate."
            ),
        )
    return DetectionResult(
        format=Format.FLAT_FILE,
        content_type=ContentType.UNKNOWN,
        confidence="low",
        reason=(
            f"Flat-file with unexpected field count ({field_count}). "
            "Layout drift or corruption — manual review required."
        ),
    )
