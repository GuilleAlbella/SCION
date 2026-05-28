from __future__ import annotations

"""Readers for Rahul's PDCR usage extracts (Pipeline 3).

Two file types live here, both delivered as §-delimited / ENDREC-
terminated flat-files alongside the dictionary extracts:

  1. ``pdcr_log_<from>_<to>.dat`` — DBQL query log.
     One record per (QueryID, SqlRowNo) fragment. SqlTextInfo may
     contain embedded newlines (multi-line SQL), so ENDREC is the
     only safe record terminator. 10 fields:

         platform_name, log_date, proc_id, collect_timestamp,
         query_id, sql_row_no, sql_text_info, default_database,
         qb_job_name, qb_proc_name

  2. ``pdcr_object_usage_<from>_<to>.dat`` — per-object usage.
     One record per (database, table, column, object_type) tuple
     with usage counters and last-access timestamp. 12 fields,
     single-line records:

         platform_name, database_name, table_name, column_name,
         data_size, object_type, count_a, count_b, count_c,
         count_d, count_e, access_timestamp

Why a separate module from `dict_flat_file_reader.py`
======================================================

The dictionary reader is opinionated about the snapshot pipeline:
its output flows into `Snapshot` / `SchemaSnapshot` / `TableSnapshot`
/ `ColumnSnapshot`, and the per-view dataclasses are shaped around
that contract. The PDCR layouts have nothing to do with snapshot
state — they describe *operational behaviour* of the warehouse and
feed `UsageEvent` / `ObjectCriticality`. Keeping the two readers
side-by-side but separate avoids dragging dict-only assumptions
(like the 16-col TPT template) into the usage path, and makes the
"what is each module responsible for" question answerable at a
glance.

We do reuse the byte-level helpers from `dict_flat_file_reader.py`
(``_split_records``, ``_split_fields``, ``_parse_int``, ``_nn``)
because the tokenising rules are identical. That's the right
sharing surface — anything more couples the two readers in ways
that would make a Pipeline 3 change ripple into the dict path.

Field-level encoding
====================

Same as the dict readers:
  - delimiter: ``§`` (U+00A7)
  - escape:    ``\\`` — literal ``§`` in data is rendered ``\\§``
  - terminator: ``ENDREC``
  - text:      UTF-8 (Latin-1 fallback handled in the streaming
               readers; never the case at customer scale so far)

This module is PURE: no DB, no I/O beyond reading the file handed
in. Persistence lives in PR-C.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from app.metadata.dict_flat_file_reader import (
    DEFAULT_FIELD_DELIMITER,
    DEFAULT_ESCAPE_CHARACTER,
    DEFAULT_RECORD_TERMINATOR,
    DictFlatFileError,
    _split_fields,
    _split_records,
    _parse_int,
    _nn,
)


# ──── Field counts ────
# These are the source of truth for the reader contracts. If Rahul
# ever changes the layout (e.g. adds an `extract_run_id` like the
# dict files), bump the constant and update the dataclass; the
# reader body needs no other change.
_DBQL_FIELD_COUNT = 10
_OBJECT_USAGE_FIELD_COUNT = 12


# ──── Exceptions ────

class PDCRFlatFileError(DictFlatFileError):
    """Raised when a PDCR flat-file row doesn't match the expected contract.

    Subclasses ``DictFlatFileError`` so the ingest pipeline can catch
    the family of "flat-file data quality" errors with one handler,
    but distinct enough to log "PDCR" vs "dict" without sniffing the
    message string.
    """


# ──── Dataclasses ────
#
# All fields are strings as they come off the wire, with explicit
# `int` for numeric columns where the downstream consumer needs to do
# arithmetic. Timestamps stay as strings here — converting to
# `datetime` happens in the persister (PR-C) where the target column
# type is known.

@dataclass(frozen=True)
class DBQLRecord:
    """One DBQL query log record (a single SqlRowNo fragment).

    A complete query is reconstructed by grouping records by
    ``query_id`` and concatenating ``sql_text_info`` in ascending
    ``sql_row_no`` order. The grouping happens in PR-C; this reader
    is intentionally one-row-at-a-time.
    """
    platform_name: str          # "Transcend-DevTest"
    log_date: str               # "2026/05/12"
    proc_id: Optional[int]      # PE/AMP process id
    collect_timestamp: str      # "2026-05-12 00:06:43.623288"
    query_id: Optional[int]     # 18-19 digit bigint
    sql_row_no: Optional[int]   # 1..N fragment number within the query
    sql_text_info: str          # SQL fragment — MAY contain embedded \n
    default_database: Optional[str]
    qb_job_name: Optional[str]  # "QueryBand" job name (often null)
    qb_proc_name: Optional[str] # "QueryBand" procedure name (often null)


@dataclass(frozen=True)
class ObjectUsageRecord:
    """One per-object usage record.

    All five count fields are emitted by Rahul's exporter; their
    precise semantics (query_count / user_count / unique_users /
    something_else) are pending confirmation. We pass them through
    untyped here so the persister (PR-C) can name them properly once
    Rahul confirms.
    """
    platform_name: str
    database_name: str
    table_name: str
    column_name: str
    data_size: Optional[str]    # "1,188" — kept raw; numeric parse in persister
    object_type: str            # "Col" / "Tbl" / "Idx" / …
    count_a: Optional[int]      # field 7  — semantics TBD
    count_b: Optional[int]      # field 8
    count_c: Optional[int]      # field 9  (often empty in practice)
    count_d: Optional[int]      # field 10
    count_e: Optional[int]      # field 11
    access_timestamp: str       # "2026-05-12 17:47:57.646670"


# ──── DBQL reader ────

def iter_dbql_log(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
    terminator: str = DEFAULT_RECORD_TERMINATOR,
) -> Iterator[DBQLRecord]:
    """Stream ``pdcr_log_*.dat`` records one at a time.

    Uses ENDREC splitting because ``sql_text_info`` (field 7) can
    contain embedded newlines (multi-line SQL). A naive line-based
    split would fragment records mid-statement; ENDREC is the only
    safe delimiter Rahul guarantees won't appear inside a value.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    for idx, record in enumerate(_split_records(raw, terminator), start=1):
        fields = _split_fields(record, delimiter, escape)
        if len(fields) != _DBQL_FIELD_COUNT:
            raise PDCRFlatFileError(
                f"{path.name}:record#{idx}: expected {_DBQL_FIELD_COUNT} fields "
                f"(pdcr_log layout), got {len(fields)}. First 200 chars: "
                f"{record[:200]!r}"
            )
        yield DBQLRecord(
            platform_name=fields[0],
            log_date=fields[1],
            proc_id=_parse_int(fields[2]),
            collect_timestamp=fields[3],
            query_id=_parse_int(fields[4]),
            sql_row_no=_parse_int(fields[5]),
            # Preserve the SQL text verbatim — including embedded
            # newlines — because the persister will re-assemble the
            # full query by SqlRowNo and downstream consumers
            # (DataDNA correlation) need byte-fidelity.
            sql_text_info=fields[6],
            default_database=_nn(fields[7]),
            qb_job_name=_nn(fields[8]),
            qb_proc_name=_nn(fields[9]),
        )


def read_dbql_log(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
    terminator: str = DEFAULT_RECORD_TERMINATOR,
) -> List[DBQLRecord]:
    """Parse a ``pdcr_log_*.dat`` file fully into memory.

    Convenience wrapper around ``iter_dbql_log``. Use the iterator
    directly when scale matters (Rahul's day-of-DBQL files are
    typically ~50-100 MB, around 50-100k records; loading into a
    list is fine but the streaming variant lets the persister batch
    inserts without holding the full file).
    """
    return list(iter_dbql_log(path, delimiter, escape, terminator))


# ──── Object Usage reader ────

def iter_object_usage(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
    terminator: str = DEFAULT_RECORD_TERMINATOR,
) -> Iterator[ObjectUsageRecord]:
    """Stream ``pdcr_object_usage_*.dat`` records.

    Single-line records (no embedded newlines in any field), but
    ENDREC is the terminator anyway — matches the producer contract
    documented in Rahul's `_export.sql` template.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    for idx, record in enumerate(_split_records(raw, terminator), start=1):
        fields = _split_fields(record, delimiter, escape)
        if len(fields) != _OBJECT_USAGE_FIELD_COUNT:
            raise PDCRFlatFileError(
                f"{path.name}:record#{idx}: expected {_OBJECT_USAGE_FIELD_COUNT} fields "
                f"(pdcr_object_usage layout), got {len(fields)}. First 200 chars: "
                f"{record[:200]!r}"
            )
        yield ObjectUsageRecord(
            platform_name=fields[0],
            database_name=fields[1],
            table_name=fields[2],
            column_name=fields[3],
            data_size=_nn(fields[4]),  # raw string like "1,188"
            object_type=fields[5],
            count_a=_parse_int(fields[6]),
            count_b=_parse_int(fields[7]),
            count_c=_parse_int(fields[8]),
            count_d=_parse_int(fields[9]),
            count_e=_parse_int(fields[10]),
            access_timestamp=fields[11],
        )


def read_object_usage(
    path: Path,
    delimiter: str = DEFAULT_FIELD_DELIMITER,
    escape: str = DEFAULT_ESCAPE_CHARACTER,
    terminator: str = DEFAULT_RECORD_TERMINATOR,
) -> List[ObjectUsageRecord]:
    """Parse a ``pdcr_object_usage_*.dat`` file fully into memory."""
    return list(iter_object_usage(path, delimiter, escape, terminator))


# ──── Convenience: DBQL query reassembly ────
#
# Lives here (rather than in the persister) so any consumer that
# needs the full SQL — debugger, validator, DataDNA correlation —
# can use it without pulling the persister in.

def reassemble_query(records: List[DBQLRecord]) -> dict[int, str]:
    """Group records by ``query_id`` and concatenate fragments.

    Returns ``{query_id: full_sql_text}``. Records are sorted by
    ``sql_row_no`` ascending within each group so the resulting SQL
    is byte-identical to what Teradata executed.

    Edge cases:
      - Records with ``query_id is None`` are silently skipped (the
        upstream producer would have warned, and we'd reject the
        upload before reaching this function in PR-D).
      - Records with ``sql_row_no is None`` sort to the end of their
        group (Python sorts ``None`` last when paired with a default
        key). This is defensive — Rahul's contract says SqlRowNo is
        always populated.
    """
    from collections import defaultdict

    groups: dict[int, List[DBQLRecord]] = defaultdict(list)
    for rec in records:
        if rec.query_id is None:
            continue
        groups[rec.query_id].append(rec)

    out: dict[int, str] = {}
    for qid, recs in groups.items():
        # Stable sort by sql_row_no; rows with None row_no go last.
        recs_sorted = sorted(recs, key=lambda r: (r.sql_row_no is None, r.sql_row_no or 0))
        # Producer contract: fragments concatenate with NO intermediate
        # character. Whitespace at boundaries is allowed (and common
        # because of how Teradata stores the original text).
        out[qid] = "".join(r.sql_text_info for r in recs_sorted)
    return out
