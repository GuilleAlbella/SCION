from __future__ import annotations

"""Reader for Rahul's data-dictionary `export` flat-files.

Each SQL template in `Parser/data_dictionary_extract/metadata_extract/` has
two variants:

  - `standard`: relational SELECT (each field as a separate column)
  - `export`:   one VARCHAR record per row, field-delimiter `§`,
                record-terminator `ENDREC`, multiline-safe via `oreplace`

SCION ingests the `export` variant because it's what the steering
committee standardised on (no direct client-DB connection). This module
parses those files back into typed Python dataclasses.

Design principles:
- **Pure**: no DB writes, no I/O beyond the file the caller hands over.
- **Order-driven**: the column order in the `export` SELECT IS the
  contract. We hardcode it per view and validate arity at parse time.
- **Lenient on trailing whitespace** (BTEQ sometimes pads) but strict
  on field count — a mismatched record count is a data-quality signal
  we must surface, not hide.
- **One public function per view** so callers can ingest them
  independently; the file boundaries map to Rahul's delivery cadence.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional


# ──── Tokens defined by Rahul's `run_metadata_extracts.py` ────
# Matching his defaults so a stock export run Just Works. If a client
# customises them, they pass them through when generating the file, so
# the parameters here are overridable per-call.
DEFAULT_FIELD_DELIMITER = "§"
DEFAULT_ESCAPE_CHARACTER = "\\"
DEFAULT_RECORD_TERMINATOR = "ENDREC"

# Every export row starts with these 5 technical fields in fixed order,
# prepended by the SQL templates before the domain-specific columns.
TECH_FIELDS = [
    "source_system_name",
    "extract_run_id",
    "extracted_at_utc",
    "snapshot_date",
    "row_hash",
]


# ──── Dataclasses — one per view, matching the export SQL column order ─

@dataclass(frozen=True)
class _TechFields:
    """Shared header fields present on every dictionary record."""
    source_system_name: str
    extract_run_id: str
    extracted_at_utc: str
    snapshot_date: str
    row_hash: str


@dataclass(frozen=True)
class DatabaseRecord:
    tech: _TechFields
    database_name: str
    owner_name: Optional[str]
    creator_name: Optional[str]
    create_timestamp: Optional[str]
    last_alter_name: Optional[str]
    last_alter_timestamp: Optional[str]
    comment_string: Optional[str]
    perm_space: Optional[str]
    spool_space: Optional[str]
    temp_space: Optional[str]
    current_perm: Optional[str]
    peak_perm: Optional[str]


@dataclass(frozen=True)
class TableRecord:
    tech: _TechFields
    database_name: str
    table_name: str
    table_kind: str                 # T/V/M/P/F/... — feeds object_type_from_tablekind
    tvm_id: Optional[str]
    creator_name: Optional[str]
    create_timestamp: Optional[str]
    last_alter_name: Optional[str]
    last_alter_timestamp: Optional[str]
    comment_string: Optional[str]
    protection_type: Optional[str]
    journal_flag: Optional[str]
    check_opt: Optional[str]


@dataclass(frozen=True)
class ColumnRecord:
    tech: _TechFields
    database_name: str
    table_name: str
    column_name: str
    column_id: Optional[int]             # ← ordinal_position
    column_type: str                     # 2-char TD code
    column_length: Optional[int]
    decimal_total_digits: Optional[int]
    decimal_fractional_digits: Optional[int]
    nullable: Optional[str]              # 'Y' / 'N'
    default_value: Optional[str]
    format: Optional[str]
    title: Optional[str]
    char_type: Optional[int]
    case_specific: Optional[str]


@dataclass(frozen=True)
class IndexRecord:
    tech: _TechFields
    database_name: str
    table_name: str
    index_name: Optional[str]
    index_number: Optional[int]
    index_type: Optional[str]
    unique_flag: Optional[str]
    primary_key_flag: Optional[str]
    column_name: str
    column_position: Optional[int]
    ordering: Optional[str]
    constraint_name: Optional[str]


@dataclass(frozen=True)
class PartitioningRecord:
    tech: _TechFields
    database_name: str
    table_name: str
    constraint_name: Optional[str]
    constraint_type: Optional[str]
    constraint_text: Optional[str]
    create_timestamp: Optional[str]
    last_alter_timestamp: Optional[str]


@dataclass(frozen=True)
class TableTextRecord:
    """A single fragment. `RequestText` is chunked by TD into multiple rows
    ordered by `request_text_seq`; the caller should concatenate in that
    order to reconstruct the full DDL. See `assemble_ddl()`.
    """
    tech: _TechFields
    database_name: str
    table_name: str
    table_kind: str
    request_text_seq: Optional[int]
    request_text: str


# ──── Column-order contracts (MUST match the export SQLs) ────
# These orderings come directly from the `_export.sql` files; if Rahul
# changes one, this is the single place to update. We validate column
# count at parse time, so a mismatch is caught immediately with a clear
# error rather than corrupted data silently downstream.

_DATABASE_COLS = TECH_FIELDS + [
    "database_name", "owner_name", "creator_name",
    "create_timestamp", "last_alter_name", "last_alter_timestamp",
    "comment_string", "perm_space", "spool_space", "temp_space",
    "current_perm", "peak_perm",
]

_TABLE_COLS = TECH_FIELDS + [
    "database_name", "table_name", "table_kind", "tvm_id",
    "creator_name", "create_timestamp", "last_alter_name",
    "last_alter_timestamp", "comment_string", "protection_type",
    "journal_flag", "check_opt",
]

_COLUMN_COLS = TECH_FIELDS + [
    "database_name", "table_name", "column_name", "column_id",
    "column_type", "column_length", "decimal_total_digits",
    "decimal_fractional_digits", "nullable", "default_value",
    "format", "title", "char_type", "case_specific",
]

_INDEX_COLS = TECH_FIELDS + [
    "database_name", "table_name", "index_name", "index_number",
    "index_type", "unique_flag", "primary_key_flag", "column_name",
    "column_position", "ordering", "constraint_name",
]

_PARTITIONING_COLS = TECH_FIELDS + [
    "database_name", "table_name", "constraint_name", "constraint_type",
    "constraint_text", "create_timestamp", "last_alter_timestamp",
]

_TABLETEXT_COLS = TECH_FIELDS + [
    "database_name", "table_name", "table_kind",
    "request_text_seq", "request_text",
]


# ──── Low-level tokenising ────

class DictFlatFileError(ValueError):
    """Raised when a flat-file row doesn't match the expected contract.

    Kept as a subclass of `ValueError` so callers can catch it broadly,
    but distinct enough that the ingest pipeline can log it with a
    specific "data quality" category rather than a generic error.
    """


def _split_records(
    raw: str,
    terminator: str,
) -> Iterator[str]:
    """Yield one record at a time.

    Records END with `terminator`; newlines within a record (from CLOB
    content like RequestText) are preserved because they appear inside
    the field, not between records. This is why the `export` variant
    exists — a naive "one record per line" would break on multiline SQL.
    """
    # Using split is fine here because the terminator is a multi-char
    # literal ("ENDREC" by default) that won't collide with data. The
    # trailing empty element (file ended with a terminator) is dropped.
    parts = raw.split(terminator)
    for p in parts:
        stripped = p.strip("\r\n\t ")
        if stripped:
            yield stripped


def _split_fields(
    record: str,
    delimiter: str,
    escape: str,
) -> List[str]:
    """Split a record into fields, honouring escaped delimiters.

    Rahul's export applies `oreplace(value, delimiter, escape+delimiter)`
    on every field before concatenating with unescaped delimiters. So
    `a§b\§c§d` should become `["a", "b§c", "d"]`: the `\§` is literal.

    We walk the string once, tracking whether the previous char was the
    escape char — cheap and correct.
    """
    out: List[str] = []
    buf: List[str] = []
    i = 0
    n = len(record)
    while i < n:
        ch = record[i]
        if ch == escape and i + 1 < n and record[i + 1] == delimiter:
            # Literal delimiter — consume both chars, emit the delimiter
            buf.append(delimiter)
            i += 2
            continue
        if ch == delimiter:
            out.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out


def _parse_int(s: Optional[str]) -> Optional[int]:
    """Permissive integer parse. Empty / whitespace-only → None."""
    if s is None:
        return None
    t = s.strip()
    if not t:
        return None
    try:
        return int(t)
    except ValueError:
        return None


def _nn(s: Optional[str]) -> Optional[str]:
    """Normalise empty-string to None (BTEQ exports empty = NULL)."""
    if s is None:
        return None
    t = s.strip()
    return t if t else None


def _tech_from(d: dict) -> _TechFields:
    return _TechFields(
        source_system_name=d["source_system_name"],
        extract_run_id=d["extract_run_id"],
        extracted_at_utc=d["extracted_at_utc"],
        snapshot_date=d["snapshot_date"],
        row_hash=d["row_hash"],
    )


def _parse_records(
    path: Path,
    expected_cols: List[str],
    delimiter: str,
    escape: str,
    terminator: str,
) -> Iterator[dict]:
    """Low-level row iterator: validate arity + return per-row dict.

    The view-specific `read_*` functions wrap this to construct the
    right dataclass. Keeping this generic avoids 6 near-identical
    tokenising loops.
    """
    raw = path.read_text(encoding="utf-8")
    for idx, record in enumerate(_split_records(raw, terminator), start=1):
        fields = _split_fields(record, delimiter, escape)
        if len(fields) != len(expected_cols):
            raise DictFlatFileError(
                f"{path.name}:record#{idx}: expected {len(expected_cols)} "
                f"fields, got {len(fields)}. First 200 chars of record: "
                f"{record[:200]!r}"
            )
        yield dict(zip(expected_cols, fields))


# ──── Public readers (one per view) ────

def read_databases(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
    terminator: str = DEFAULT_RECORD_TERMINATOR,
) -> List[DatabaseRecord]:
    """Parse a `databasesv_*_export.sql` output file."""
    out: List[DatabaseRecord] = []
    for d in _parse_records(path, _DATABASE_COLS, delimiter, escape, terminator):
        out.append(DatabaseRecord(
            tech=_tech_from(d),
            database_name=d["database_name"],
            owner_name=_nn(d["owner_name"]),
            creator_name=_nn(d["creator_name"]),
            create_timestamp=_nn(d["create_timestamp"]),
            last_alter_name=_nn(d["last_alter_name"]),
            last_alter_timestamp=_nn(d["last_alter_timestamp"]),
            comment_string=_nn(d["comment_string"]),
            perm_space=_nn(d["perm_space"]),
            spool_space=_nn(d["spool_space"]),
            temp_space=_nn(d["temp_space"]),
            current_perm=_nn(d["current_perm"]),
            peak_perm=_nn(d["peak_perm"]),
        ))
    return out


def read_tables(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
    terminator: str = DEFAULT_RECORD_TERMINATOR,
) -> List[TableRecord]:
    out: List[TableRecord] = []
    for d in _parse_records(path, _TABLE_COLS, delimiter, escape, terminator):
        out.append(TableRecord(
            tech=_tech_from(d),
            database_name=d["database_name"],
            table_name=d["table_name"],
            table_kind=d["table_kind"],
            tvm_id=_nn(d["tvm_id"]),
            creator_name=_nn(d["creator_name"]),
            create_timestamp=_nn(d["create_timestamp"]),
            last_alter_name=_nn(d["last_alter_name"]),
            last_alter_timestamp=_nn(d["last_alter_timestamp"]),
            comment_string=_nn(d["comment_string"]),
            protection_type=_nn(d["protection_type"]),
            journal_flag=_nn(d["journal_flag"]),
            check_opt=_nn(d["check_opt"]),
        ))
    return out


def read_columns(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
    terminator: str = DEFAULT_RECORD_TERMINATOR,
) -> List[ColumnRecord]:
    out: List[ColumnRecord] = []
    for d in _parse_records(path, _COLUMN_COLS, delimiter, escape, terminator):
        out.append(ColumnRecord(
            tech=_tech_from(d),
            database_name=d["database_name"],
            table_name=d["table_name"],
            column_name=d["column_name"],
            column_id=_parse_int(d["column_id"]),
            column_type=d["column_type"],
            column_length=_parse_int(d["column_length"]),
            decimal_total_digits=_parse_int(d["decimal_total_digits"]),
            decimal_fractional_digits=_parse_int(d["decimal_fractional_digits"]),
            nullable=_nn(d["nullable"]),
            default_value=_nn(d["default_value"]),
            format=_nn(d["format"]),
            title=_nn(d["title"]),
            char_type=_parse_int(d["char_type"]),
            case_specific=_nn(d["case_specific"]),
        ))
    return out


def read_indices(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
    terminator: str = DEFAULT_RECORD_TERMINATOR,
) -> List[IndexRecord]:
    out: List[IndexRecord] = []
    for d in _parse_records(path, _INDEX_COLS, delimiter, escape, terminator):
        out.append(IndexRecord(
            tech=_tech_from(d),
            database_name=d["database_name"],
            table_name=d["table_name"],
            index_name=_nn(d["index_name"]),
            index_number=_parse_int(d["index_number"]),
            index_type=_nn(d["index_type"]),
            unique_flag=_nn(d["unique_flag"]),
            primary_key_flag=_nn(d["primary_key_flag"]),
            column_name=d["column_name"],
            column_position=_parse_int(d["column_position"]),
            ordering=_nn(d["ordering"]),
            constraint_name=_nn(d["constraint_name"]),
        ))
    return out


def read_partitioning(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
    terminator: str = DEFAULT_RECORD_TERMINATOR,
) -> List[PartitioningRecord]:
    out: List[PartitioningRecord] = []
    for d in _parse_records(path, _PARTITIONING_COLS, delimiter, escape, terminator):
        out.append(PartitioningRecord(
            tech=_tech_from(d),
            database_name=d["database_name"],
            table_name=d["table_name"],
            constraint_name=_nn(d["constraint_name"]),
            constraint_type=_nn(d["constraint_type"]),
            constraint_text=_nn(d["constraint_text"]),
            create_timestamp=_nn(d["create_timestamp"]),
            last_alter_timestamp=_nn(d["last_alter_timestamp"]),
        ))
    return out


def read_tabletext(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
    terminator: str = DEFAULT_RECORD_TERMINATOR,
) -> List[TableTextRecord]:
    out: List[TableTextRecord] = []
    for d in _parse_records(path, _TABLETEXT_COLS, delimiter, escape, terminator):
        out.append(TableTextRecord(
            tech=_tech_from(d),
            database_name=d["database_name"],
            table_name=d["table_name"],
            table_kind=d["table_kind"],
            request_text_seq=_parse_int(d["request_text_seq"]),
            request_text=d["request_text"],
        ))
    return out


# ──── Convenience ────

def assemble_ddl(rows: List[TableTextRecord]) -> dict[tuple[str, str], str]:
    """Reconstruct per-object DDL by concatenating RequestText fragments.

    DBC.TableTextV chunks the `RequestText` of a view/macro/proc into
    multiple rows ordered by `request_text_seq`. Consumers that need the
    DDL as one string (our DDL Generator, TAISA context builder) call
    this. Keyed by `(database_name, table_name)` so lookups are cheap.
    """
    by_obj: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for r in rows:
        key = (r.database_name, r.table_name)
        by_obj.setdefault(key, []).append((r.request_text_seq or 0, r.request_text))
    return {
        key: "".join(txt for _, txt in sorted(frags, key=lambda p: p[0]))
        for key, frags in by_obj.items()
    }
