from __future__ import annotations

"""Reader for Rahul's data-dictionary `export` flat-files.

Rahul's extractor produces six files per extraction run:

  1. databasesv_*_export.rendered.dat              — DBC.DatabasesV
  2. tablesv_*_export.rendered.dat                 — DBC.TablesV
  3. columnsv_*_export.rendered.dat                — DBC.ColumnsV
  4. indicesv_*_export.rendered.dat                — DBC.IndicesV
  5. partitioningconstraintsv_*_export.rendered.dat — DBC.PartitioningConstraintsV
  6. tabletextv_*_export.rendered.dat              — DBC.TableTextV (special)

The first five share a **fixed 16-column layout** (`col_01`..`col_16`)
designed for TPT's DataConnector consumer. Unused trailing slots are
left blank (`§§§`) so every record has the same arity. This is by
design — it lets one TPT script handle all five views.

`tabletextv` is the odd one out: a single concatenated record column
terminated by `ENDREC`, because the `RequestText` payload contains
embedded newlines that would otherwise break record boundaries.

Field-level encoding (per Rahul's README):
- delimiter: `§` (U+00A7)
- escape:    `\` — literal `§` in data is rendered `\§`
- terminator (tabletext only): `ENDREC`
- text:      UTF-8

Design principles
- **Pure**: no DB writes, no I/O beyond the file handed in.
- **Order-driven**: `col_01`..`col_16` ordering IS the contract; we
  validate arity at parse time so a layout drift surfaces immediately.
- **Lenient on whitespace** (BTEQ pads), **strict on field count**.
- **One public function per view** — independently consumable.

If Rahul ever changes the 16-col layout (e.g. promotes a blank to a
real field), bumping the `_VIEW_FIELD_MAP` below is the only edit
needed; the dataclasses + readers fall out of it.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional


# ──── Format tokens (Rahul's defaults from run_metadata_extracts.py) ────
DEFAULT_FIELD_DELIMITER = "§"
DEFAULT_ESCAPE_CHARACTER = "\\"
DEFAULT_RECORD_TERMINATOR = "ENDREC"

# ──── Standard 16-column layout (5 of 6 files use this) ────
# Every record starts with these 4 technical fields (col_01..col_04).
# col_05..col_16 are view-specific (or blank fillers).
_STANDARD_TECH_FIELDS = [
    "source_system_name",   # col_01: e.g. "Transcend-DevTest"
    "extract_run_id",       # col_02: timestamp + UUID, generated once per run
    "extracted_at_utc",     # col_03: current_timestamp(6) at extract time
    "snapshot_date",        # col_04: cast(current_timestamp as date)
]
_STANDARD_FIELD_COUNT = 16  # col_01..col_16 — fixed by TPT job template

# ──── Per-view mapping: position-in-16-col-row -> dataclass attribute ──
# Only positions actually populated by Rahul's `_export.sql` are listed.
# Blank fillers (col_15/col_16 for some views) are intentionally absent.
# Source: README.md in `Parser/Data extract 2/`.

_DATABASES_FIELDS = {
    # col_05..col_14, col_15+col_16 are blank fillers
    5:  "database_name",
    6:  "owner_name",
    7:  "creator_name",
    8:  "create_timestamp",
    9:  "last_alter_name",
    10: "last_alter_timestamp",
    11: "comment_string",
    12: "perm_space",
    13: "spool_space",
    14: "temp_space",
}

_TABLES_FIELDS = {
    # col_05..col_15, col_16 is blank filler
    5:  "database_name",
    6:  "table_name",
    7:  "table_kind",   # T/V/M/P/F/... — feeds object_type_from_tablekind
    8:  "creator_name",
    9:  "create_timestamp",
    10: "last_alter_name",
    11: "last_alter_timestamp",
    12: "comment_string",
    13: "protection_type",
    14: "journal_flag",
    15: "check_opt",
}

_COLUMNS_FIELDS = {
    # col_05..col_16 (all 12 used)
    5:  "database_name",
    6:  "table_name",
    7:  "column_name",
    8:  "column_id",
    9:  "column_type",     # 2-char TD code (CV, I, DA, ...)
    10: "column_length",
    11: "decimal_total_digits",
    12: "decimal_fractional_digits",
    13: "nullable",
    14: "default_value",
    15: "char_type",
    16: "uppercase_flag",
}

_INDICES_FIELDS = {
    # col_05..col_12, col_13..col_16 are blank fillers
    5:  "database_name",
    6:  "table_name",
    7:  "index_name",
    8:  "index_number",
    9:  "index_type",      # P (primary), S (secondary), U (unique), etc.
    10: "unique_flag",     # Y/N
    11: "column_name",
    12: "column_position",
}

_PARTITIONING_FIELDS = {
    # col_05..col_09, col_10..col_16 are blank fillers
    5: "database_name",
    6: "table_name",
    7: "constraint_type",
    8: "constraint_text",
    9: "create_timestamp",
}

# ──── TableTextV — special 9-column layout, ENDREC terminator ────
# README §"TableTextV extract (single record column)": the export still
# concatenates its 9 logical fields with `§`, but uses `ENDREC` between
# records so embedded newlines in RequestText survive.
_TABLETEXT_FIELDS = [
    "source_system_name",
    "extract_run_id",
    "extracted_at_utc",
    "snapshot_date",
    "database_name",
    "table_name",
    "table_kind",
    "request_text_seq",
    "request_text",
]


# ──── Dataclasses ────

@dataclass(frozen=True)
class TechFields:
    """Shared header on every dictionary record. The combination
    `(source_system_name, extract_run_id)` uniquely identifies the
    extraction run — SCION uses this as the snapshot key."""
    source_system_name: str
    extract_run_id: str
    extracted_at_utc: str
    snapshot_date: str


@dataclass(frozen=True)
class DatabaseRecord:
    tech: TechFields
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


@dataclass(frozen=True)
class TableRecord:
    tech: TechFields
    database_name: str
    table_name: str
    table_kind: str
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
    tech: TechFields
    database_name: str
    table_name: str
    column_name: str
    column_id: Optional[int]              # ordinal_position
    column_type: str                      # 2-char TD code
    column_length: Optional[int]
    decimal_total_digits: Optional[int]
    decimal_fractional_digits: Optional[int]
    nullable: Optional[str]               # 'Y' / 'N'
    default_value: Optional[str]
    char_type: Optional[int]
    uppercase_flag: Optional[str]


@dataclass(frozen=True)
class IndexRecord:
    tech: TechFields
    database_name: str
    table_name: str
    index_name: Optional[str]
    index_number: Optional[int]
    index_type: Optional[str]
    unique_flag: Optional[str]
    column_name: str
    column_position: Optional[int]


@dataclass(frozen=True)
class PartitioningRecord:
    tech: TechFields
    database_name: str
    table_name: str
    constraint_type: Optional[str]
    constraint_text: Optional[str]
    create_timestamp: Optional[str]


@dataclass(frozen=True)
class TableTextRecord:
    """A single fragment of a DDL statement.

    `request_text_seq` (col_08, originally `LineNo`) orders multiple
    fragments belonging to the same object — the caller concatenates
    them in that order to reconstruct the full DDL. See `assemble_ddl()`.
    """
    tech: TechFields
    database_name: str
    table_name: str
    table_kind: str
    request_text_seq: Optional[int]
    request_text: str


# ──── Errors ────

class DictFlatFileError(ValueError):
    """Raised when a flat-file row doesn't match the expected contract.

    Subclass of `ValueError` so callers can catch broadly, but distinct
    enough that the ingest pipeline can log it as "data quality" rather
    than a generic error.
    """


# ──── Low-level tokenising ────

def _split_records(raw: str, terminator: str) -> Iterator[str]:
    """Yield one record at a time using the configured terminator.

    For tabletext that's `ENDREC` (so embedded newlines in RequestText
    survive). For standard 16-col files it's the line terminator (`\\n`),
    which is what `splitlines` uses. The caller decides.
    """
    if terminator == "\n":
        # Standard 16-col layout — one record per line, no embedded
        # newlines because everything is metadata (no CLOBs).
        for line in raw.splitlines():
            stripped = line.strip("\r\n\t ")
            if stripped:
                yield stripped
    else:
        # Multi-char terminator (ENDREC). split() works because ENDREC
        # is unique enough not to appear in field values; the trailing
        # empty element after the final terminator is dropped.
        for part in raw.split(terminator):
            stripped = part.strip("\r\n\t ")
            if stripped:
                yield stripped


def _split_fields(record: str, delimiter: str, escape: str) -> List[str]:
    """Split a record into fields, honouring escaped delimiters.

    Rahul's export applies `oreplace(value, delimiter, escape+delimiter)`
    on every field before concatenating with unescaped delimiters. So
    `a§b\\§c§d` → `["a", "b§c", "d"]`: the `\\§` is literal data.
    """
    out: List[str] = []
    buf: List[str] = []
    i, n = 0, len(record)
    while i < n:
        ch = record[i]
        if ch == escape and i + 1 < n and record[i + 1] == delimiter:
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
    """Permissive integer parse. Empty or non-numeric → None.

    BTEQ exports numeric values with thousand separators (e.g.
    `378,910,604,592`). We strip commas before parsing because those
    represent display formatting, not the actual integer.
    """
    if s is None:
        return None
    t = s.strip().replace(",", "")
    if not t:
        return None
    try:
        return int(t)
    except ValueError:
        return None


def _nn(s: Optional[str]) -> Optional[str]:
    """Empty/whitespace-only → None (BTEQ exports empty for SQL NULL)."""
    if s is None:
        return None
    t = s.strip()
    return t if t else None


# ──── Standard 16-col parser (5 of 6 files) ────

def _tech_from_standard(fields: List[str]) -> TechFields:
    return TechFields(
        source_system_name=fields[0],
        extract_run_id=fields[1],
        extracted_at_utc=fields[2],
        snapshot_date=fields[3],
    )


def _parse_standard(
    path: Path,
    delimiter: str,
    escape: str,
) -> Iterator[List[str]]:
    """Yield validated 16-field rows for a standard export file.

    Validation: every emitted record has exactly 16 fields.

    Multi-line records: Rahul's standard export uses `\n` as the
    record terminator and `§` as the field delimiter, but **does not
    escape literal newlines inside field values**. That works in
    practice for `databases/columns/indices/partitioning` because
    those views' fields don't contain free-form text — but
    `tables.CommentString` is free-form, and at least one record in
    the full Transcend-DevTest extract (`DBC.AccLogRule`, a system
    macro) has a multi-line comment. The single-line assumption used
    to crash the parser at record #15125 with "got 12 fields".

    To handle this without forcing Rahul to change the export, we
    accumulate raw lines into a buffer and only emit a record once
    its parsed field count hits exactly `_STANDARD_FIELD_COUNT`. A
    line that's truly malformed (e.g. corrupt, > 16 fields) still
    raises immediately. This is the same record-recovery pattern
    RFC-4180 CSV parsers use for quoted multi-line fields, except
    here our delimiter for "where does this record end" is field
    count rather than a closing quote.

    Streaming: opens the file with a line iterator instead of
    `read_text()` so we never hold the whole file in memory. Critical
    for the columns view at production scale (Transcend-DevTest's
    full extract is 1.9 GB / 9.8M rows — `read_text()` would
    allocate ~4 GB before we even start parsing).
    """
    with path.open("r", encoding="utf-8") as fh:
        buf = ""
        record_idx = 0
        for raw_line in fh:
            # Append the raw line including its trailing newline. If
            # the record turns out to span multiple lines, we want the
            # `\n` preserved inside the comment field — that's what
            # the data actually contained.
            buf += raw_line

            # Cheap fast-path: if buf is just blank lines, reset and
            # move on. Catches empty-line padding that Rahul's
            # exporter occasionally leaves at the end of the file.
            stripped = buf.strip("\r\n\t ")
            if not stripped:
                buf = ""
                continue

            fields = _split_fields(stripped, delimiter, escape)
            n = len(fields)

            if n < _STANDARD_FIELD_COUNT:
                # Record continues on the next line — keep buffering.
                # No yield yet.
                continue

            if n > _STANDARD_FIELD_COUNT:
                # We overshot 16 fields. Either Rahul changed the
                # layout (real schema drift) or the previous record
                # was missing a delimiter and we merged it with this
                # one. Either way it's not safely recoverable —
                # better to fail loudly with a precise locator than
                # silently miscolumn data.
                record_idx += 1
                raise DictFlatFileError(
                    f"{path.name}:record#{record_idx}: expected "
                    f"{_STANDARD_FIELD_COUNT} fields (16-col layout), "
                    f"got {n} — too many fields, likely a delimiter "
                    f"escape issue or layout drift. First 200 chars: "
                    f"{stripped[:200]!r}"
                )

            # Exactly 16. Emit and reset the buffer for the next
            # record.
            record_idx += 1
            yield fields
            buf = ""

        # End of file: anything left in the buffer means the last
        # record is incomplete. Don't silently drop it.
        leftover = buf.strip("\r\n\t ")
        if leftover:
            fields = _split_fields(leftover, delimiter, escape)
            n = len(fields)
            if n == _STANDARD_FIELD_COUNT:
                # Final record without a trailing newline — valid.
                record_idx += 1
                yield fields
            else:
                raise DictFlatFileError(
                    f"{path.name}:record#{record_idx + 1}: incomplete "
                    f"final record ({n} fields, expected "
                    f"{_STANDARD_FIELD_COUNT}). File may have been "
                    f"truncated. First 200 chars: {leftover[:200]!r}"
                )


def _get(fields: List[str], col_idx_1based: int) -> Optional[str]:
    """Helper: pull col_NN (1-based) out of the 16-field row, normalised
    to None if blank. Centralises the off-by-one and the empty-string
    normalisation so the readers below stay declarative."""
    return _nn(fields[col_idx_1based - 1])


# ──── Public readers ────
# Each view exposes both a streaming `iter_*` generator and a
# materialising `read_*` (which is just `list(iter_*(...))`). The
# persister uses `iter_*` for the large views (columns, indices) so we
# never hold a full ColumnRecord list in memory; small views still use
# `read_*` because the simpler list semantics make the persist code
# easier to reason about. The dataclass shape is identical either way.


def iter_databases(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
) -> Iterator[DatabaseRecord]:
    """Stream `databasesv_*_export.rendered.dat` records one at a time."""
    for f in _parse_standard(path, delimiter, escape):
        yield DatabaseRecord(
            tech=_tech_from_standard(f),
            database_name=f[4],   # col_05 — required, even if "blank"
            owner_name=_get(f, 6),
            creator_name=_get(f, 7),
            create_timestamp=_get(f, 8),
            last_alter_name=_get(f, 9),
            last_alter_timestamp=_get(f, 10),
            comment_string=_get(f, 11),
            perm_space=_get(f, 12),
            spool_space=_get(f, 13),
            temp_space=_get(f, 14),
        )


def read_databases(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
) -> List[DatabaseRecord]:
    """Parse a `databasesv_*_export.rendered.dat` file."""
    return list(iter_databases(path, delimiter, escape))


def iter_tables(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
) -> Iterator[TableRecord]:
    """Stream `tablesv_*_export.rendered.dat` records one at a time."""
    for f in _parse_standard(path, delimiter, escape):
        yield TableRecord(
            tech=_tech_from_standard(f),
            database_name=f[4],
            table_name=f[5],
            table_kind=f[6],
            creator_name=_get(f, 8),
            create_timestamp=_get(f, 9),
            last_alter_name=_get(f, 10),
            last_alter_timestamp=_get(f, 11),
            comment_string=_get(f, 12),
            protection_type=_get(f, 13),
            journal_flag=_get(f, 14),
            check_opt=_get(f, 15),
        )


def read_tables(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
) -> List[TableRecord]:
    """Parse a `tablesv_*_export.rendered.dat` file."""
    return list(iter_tables(path, delimiter, escape))


def iter_columns(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
) -> Iterator[ColumnRecord]:
    """Stream `columnsv_*_export.rendered.dat` records one at a time.

    This is the hot path at production scale — Transcend-DevTest's
    full extract is 9.8M columns / 1.9 GB. The persister consumes
    this iterator in batches and feeds them to
    `bulk_insert_mappings` so neither parsed-record list nor ORM
    identity-map grow unbounded.
    """
    for f in _parse_standard(path, delimiter, escape):
        yield ColumnRecord(
            tech=_tech_from_standard(f),
            database_name=f[4],
            table_name=f[5],
            column_name=f[6],
            column_id=_parse_int(f[7]),
            column_type=f[8],
            column_length=_parse_int(f[9]),
            decimal_total_digits=_parse_int(f[10]),
            decimal_fractional_digits=_parse_int(f[11]),
            nullable=_get(f, 13),
            default_value=_get(f, 14),
            char_type=_parse_int(f[14]),
            uppercase_flag=_get(f, 16),
        )


def read_columns(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
) -> List[ColumnRecord]:
    """Parse a `columnsv_*_export.rendered.dat` file.

    NOTE: materialises the full list — only safe for small extracts.
    Production callers should use `iter_columns()` instead. Kept as
    a convenience for tests and the smoke-test script.
    """
    return list(iter_columns(path, delimiter, escape))


def iter_indices(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
) -> Iterator[IndexRecord]:
    """Stream `indicesv_*_export.rendered.dat` records one at a time.

    Each row is one (index, column) pair. Multi-column indexes appear
    as multiple rows with the same `index_name` / `index_number` and
    increasing `column_position`.
    """
    for f in _parse_standard(path, delimiter, escape):
        yield IndexRecord(
            tech=_tech_from_standard(f),
            database_name=f[4],
            table_name=f[5],
            index_name=_get(f, 7),
            index_number=_parse_int(f[7]),
            index_type=_get(f, 9),
            unique_flag=_get(f, 10),
            column_name=f[10],
            column_position=_parse_int(f[11]),
        )


def read_indices(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
) -> List[IndexRecord]:
    """Parse an `indicesv_*_export.rendered.dat` file."""
    return list(iter_indices(path, delimiter, escape))


def read_partitioning(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
) -> List[PartitioningRecord]:
    """Parse a `partitioningconstraintsv_*_export.rendered.dat` file."""
    out: List[PartitioningRecord] = []
    for f in _parse_standard(path, delimiter, escape):
        out.append(PartitioningRecord(
            tech=_tech_from_standard(f),
            database_name=f[4],
            table_name=f[5],
            constraint_type=_get(f, 7),
            constraint_text=_get(f, 8),
            create_timestamp=_get(f, 9),
        ))
    return out


# ──── TableText reader (custom layout: 9 fields, ENDREC-terminated) ────

def read_tabletext(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
    terminator: str = DEFAULT_RECORD_TERMINATOR,
) -> List[TableTextRecord]:
    """Parse a `tabletextv_*_export.rendered.dat` file.

    Different from the other 5: ENDREC terminator (because RequestText
    has embedded newlines) and 9-field layout instead of 16.
    """
    out: List[TableTextRecord] = []
    expected = len(_TABLETEXT_FIELDS)
    raw = path.read_text(encoding="utf-8")
    for idx, record in enumerate(_split_records(raw, terminator), start=1):
        fields = _split_fields(record, delimiter, escape)
        if len(fields) != expected:
            raise DictFlatFileError(
                f"{path.name}:record#{idx}: expected {expected} fields "
                f"(tabletext layout), got {len(fields)}. First 200 chars: "
                f"{record[:200]!r}"
            )
        out.append(TableTextRecord(
            tech=TechFields(
                source_system_name=fields[0],
                extract_run_id=fields[1],
                extracted_at_utc=fields[2],
                snapshot_date=fields[3],
            ),
            database_name=fields[4],
            table_name=fields[5],
            table_kind=fields[6],
            request_text_seq=_parse_int(fields[7]),
            request_text=fields[8],
        ))
    return out


# ──── DDL assembly convenience ────

def assemble_ddl(rows: List[TableTextRecord]) -> dict[tuple[str, str], str]:
    """Reconstruct per-object DDL by concatenating RequestText fragments.

    DBC.TableTextV chunks each `RequestText` into multiple rows ordered
    by `LineNo` (we expose it as `request_text_seq`). Consumers that
    need the full DDL as one string call this. Keyed by
    `(database_name, table_name)` for cheap lookups.
    """
    by_obj: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for r in rows:
        key = (r.database_name, r.table_name)
        by_obj.setdefault(key, []).append((r.request_text_seq or 0, r.request_text))
    return {
        key: "".join(txt for _, txt in sorted(frags, key=lambda p: p[0]))
        for key, frags in by_obj.items()
    }
