"""Persisters for PDCR ingest (Pipeline 3, PR-C).

Two entry points, one per PDCR layout:

  - ``persist_dbql_log(records, session)`` — reassembles SQL by
    QueryID and writes one ``DBQLQuery`` row per query.
  - ``persist_object_usage(records, session, snapshot_id=None)`` —
    converts PDCR per-object rows into ``UsageEvent`` rows,
    resolving identifiers case-insensitively against ``graph_node``
    for the target snapshot (when provided).

Plus one helper:

  - ``build_node_index(snapshot_id, session)`` — returns a
    case-insensitive lookup map from
    ``(database_name, object_name)`` to ``graph_node.node_id``.
    Used by the object_usage persister and re-usable by the
    criticality re-compute that lands in PR-E.

Design choices
==============

**Idempotency by natural key.** Re-running the persister on the
same input file produces zero new rows (the unique constraint on
``DBQLQuery(query_id, collect_timestamp)`` rejects the duplicate).
This is the contract every Pipeline 3 caller relies on — if the
user uploads the same `.dat` twice the second is a no-op.

**Case-insensitive identifier resolution.** PDCR emits identifiers
in UPPERCASE (Teradata internal convention) while the dictionary
preserves the original case from ``CREATE TABLE``. A naive
case-sensitive join misses ~63% of PDCR records against a real
Transcend extract (measured before this PR landed). The resolution
function lowercases on both sides.

**Skip-with-count, not fail-fast on orphans.** When a PDCR row
references an object that isn't in the snapshot's graph (genuine
drift between the 12-day-old PDCR file and the 25-day-old dict
extract, or volatile/temp tables that never enter the dict), we
skip the row and increment a counter. The caller sees the count
back in the response and can decide whether that's acceptable for
this load. This is FR-13 compliance: never silently lose data,
always quantify what was dropped and why.

**No schema_id link inserted yet.** ``UsageEvent`` has no
``graph_node_id`` foreign key today. We rely on
``(schema_name, object_name)`` string matching at query time. Adding
the FK is a v1.22 follow-up; it would let the criticality engine
do its joins by integer instead of by collated string.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.graph.graph_models import GraphNode
from app.metadata.pdcr_flat_file_reader import (
    DBQLRecord,
    ObjectUsageRecord,
    reassemble_query,
)
from app.usage.dbql_models import DBQLQuery
from app.usage.usage_models import UsageEvent


_logger = logging.getLogger(__name__)


# ──── Object type mapping ────
#
# PDCR `object_usage` carries 20 distinct object_type codes (verified
# against the 28 May 2026 Transcend extract). Six of them map cleanly
# to SCION's existing graph-node vocabulary; the remaining 14 need
# product-side decisions about whether they're worth modelling as
# new node kinds. Until that happens this PR skips them and counts
# how many were skipped per type so the caller knows what's missing.
#
# The values on the right side are the strings SCION already uses in
# ``GraphNode.object_type`` / ``UsageEvent.object_type``.
_PDCR_TYPE_TO_SCION = {
    "Col": "COLUMN",     # column-level row
    "Tab": "TABLE",      # set/multiset table
    "Viw": "VIEW",
    "Idx": "INDEX",
    "Mac": "MACRO",
    "Vol": "VOLATILE",
}

# Types we deliberately skip in this PR. Listed explicitly so a
# diff against this set is the audit trail of "what we considered
# and chose not to support yet".
_PDCR_TYPES_SKIPPED = {
    "Agg",   # aggregate join index
    "Aut",   # authentication object — not warehouse content
    "DB",    # database-level row (we model schemas, not the DB itself)
    "JIx",   # join index — graph doesn't model these yet
    "SP",    # stored procedure
    "SUF",   # user-defined function-set
    "Svr",   # foreign server reference
    "TbC",   # table check constraint
    "TbF",   # table function
    "TbO",   # table operator
    "Tmp",   # temporary table — by definition out of scope
    "UDF",   # user-defined function
    "UDM",   # user-defined method
    "XSP",   # external stored procedure
}


# ──── Public result shape ────

@dataclass
class PDCRPersistResult:
    """Summary of what a persister did.

    Returned to the caller (and ultimately to the API response in
    PR-D) so operators see exactly what landed and what didn't —
    FR-13 graceful-out-of-scope handling.
    """
    inserted: int = 0
    skipped_duplicate: int = 0
    skipped_unmapped_type: int = 0
    skipped_orphan: int = 0   # identifier not present in the snapshot graph
    skipped_invalid: int = 0  # missing required field, parse error, etc.
    # Per-PDCR-type skip counts, e.g. {"UDF": 142, "SP": 38}. Lets the
    # operator see "we ignored 180 rows of UDF / SP usage" rather than
    # just "180 skipped".
    skipped_by_type: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.skipped_by_type is None:
            self.skipped_by_type = {}


# ──── DBQL persister ────

def persist_dbql_log(
    records: Iterable[DBQLRecord],
    session: Session,
) -> PDCRPersistResult:
    """Reassemble + persist DBQL records as one row per query.

    Steps:
      1. Materialise ``records`` (we need to iterate twice — once to
         group by query_id, once after reassembly to find the
         canonical row that owns each query's metadata).
      2. Group by query_id and reassemble SQL text via
         ``reassemble_query``.
      3. For each query, write one ``DBQLQuery`` row. Metadata
         (collect_timestamp, log_date, proc_id, default_database,
         qb_*) comes from the *first* record by SqlRowNo — they're
         constant across fragments by Teradata's contract.
      4. ``session.flush()`` so the unique constraint surfaces
         conflicts inside this function rather than at the outer
         commit. Conflicts become "skipped_duplicate" in the result.

    The function does NOT commit; the caller controls transaction
    boundaries. That matches the convention of every other persister
    in the backend.
    """
    result = PDCRPersistResult()

    # Materialise so we can iterate twice. PDCR files top out at ~50k
    # records per day-window which fits comfortably in memory.
    rec_list = list(records)
    if not rec_list:
        return result

    # Group by query_id; reassemble_query already does this but
    # silently drops null-query_id rows. We also need the metadata
    # from the row with sql_row_no=1 (or the lowest available), so
    # we keep our own grouping alongside.
    by_query: dict[int, list[DBQLRecord]] = defaultdict(list)
    for r in rec_list:
        if r.query_id is None:
            result.skipped_invalid += 1
            continue
        by_query[r.query_id].append(r)

    reassembled = reassemble_query(rec_list)

    # Pre-load existing (query_id, collect_timestamp) pairs so we can
    # report "skipped_duplicate" without slamming the DB with one
    # SELECT per query. Chunked at 900 because of SQLite's host-param
    # ceiling — same convention as the rest of the codebase.
    existing_keys: set[tuple[int, datetime]] = set()
    query_ids = list(by_query.keys())
    for i in range(0, len(query_ids), 900):
        chunk = query_ids[i : i + 900]
        rows = session.execute(
            select(DBQLQuery.query_id, DBQLQuery.collect_timestamp).where(
                DBQLQuery.query_id.in_(chunk)
            )
        ).all()
        existing_keys.update((qid, ts) for qid, ts in rows)

    for qid, fragments in by_query.items():
        # Sort by sql_row_no; the first fragment carries the canonical
        # metadata. Records with null row_no go last (defensive — the
        # producer contract says SqlRowNo is always populated).
        fragments.sort(key=lambda r: (r.sql_row_no is None, r.sql_row_no or 0))
        head = fragments[0]

        collect_ts = _parse_timestamp(head.collect_timestamp)
        log_date = _parse_date(head.log_date)
        if collect_ts is None or log_date is None:
            result.skipped_invalid += 1
            continue

        if (qid, collect_ts) in existing_keys:
            result.skipped_duplicate += 1
            continue

        session.add(
            DBQLQuery(
                query_id=qid,
                collect_timestamp=collect_ts,
                log_date=log_date,
                proc_id=head.proc_id,
                sql_text=reassembled[qid],
                default_database=head.default_database,
                qb_job_name=head.qb_job_name,
                qb_proc_name=head.qb_proc_name,
                platform_name=head.platform_name,
            )
        )
        existing_keys.add((qid, collect_ts))
        result.inserted += 1

    session.flush()
    _logger.info(
        "persist_dbql_log: inserted=%d skipped_duplicate=%d skipped_invalid=%d",
        result.inserted,
        result.skipped_duplicate,
        result.skipped_invalid,
    )
    return result


# ──── Object Usage persister ────

def persist_object_usage(
    records: Iterable[ObjectUsageRecord],
    session: Session,
    snapshot_id: Optional[int] = None,
) -> PDCRPersistResult:
    """Convert PDCR per-object rows into ``UsageEvent`` rows.

    When ``snapshot_id`` is provided the persister also resolves each
    record's (database, table, column) tuple against ``graph_node``
    case-insensitively. Unresolved identifiers are counted as orphans
    and skipped. When ``snapshot_id`` is None we accept every row
    blindly (useful for the v1.22 case where usage arrives before
    any dict snapshot exists).

    Count mapping (confirmed by Rahul, 2026-06-02 / 8 May README):
    ``query_count`` ← ``QueryCount`` and ``user_count`` ←
    ``DistinctUserCount``. The other numerics (FreqofUse, TypeOfUse,
    TargetIndicator) are stashed in ``source_json`` for traceability.
    Because PDCR aggregates by ``(database, table, column, ObjectNum,
    TypeOfUse)``, an object can span several rows (one per TypeOfUse);
    rolling up per object is done at query time in /usage/summary and
    /usage/object via ``SUM(query_count)`` + ``MAX(user_count)``, so we
    persist each row as-is here.
    """
    result = PDCRPersistResult()

    rec_list = list(records)
    if not rec_list:
        return result

    # Build the CI lookup map once for the whole batch — re-querying
    # per-row would be O(N×|graph_node|) on Transcend = unworkable.
    node_index: dict[tuple[str, str], int] = (
        build_node_index(snapshot_id, session) if snapshot_id else {}
    )

    for r in rec_list:
        # Skip object types we don't model yet (UDF / SP / Tmp / etc).
        scion_type = _PDCR_TYPE_TO_SCION.get(r.object_type)
        if scion_type is None:
            result.skipped_unmapped_type += 1
            result.skipped_by_type[r.object_type] = (
                result.skipped_by_type.get(r.object_type, 0) + 1
            )
            continue

        access_ts = _parse_timestamp(r.last_accessed)
        if access_ts is None:
            result.skipped_invalid += 1
            continue

        # For column-level rows the "object name" is the column;
        # for table-level rows it's the table. The persister normalises
        # so downstream consumers can join uniformly on
        # ``(schema_name, object_name)``.
        if scion_type == "COLUMN":
            object_name = r.column_name
        else:
            object_name = r.table_name

        # Case-insensitive resolve. We only enforce orphan filtering
        # when caller passed a snapshot_id — otherwise accept everything.
        if snapshot_id is not None:
            key = (r.database_name.lower(), object_name.lower())
            if key not in node_index:
                result.skipped_orphan += 1
                continue

        # Confirmed count semantics (see module docstring).
        query_count = r.query_count if r.query_count is not None else 0
        user_count = r.distinct_user_count if r.distinct_user_count is not None else 0

        session.add(
            UsageEvent(
                object_name=object_name,
                object_type=scion_type,
                schema_name=r.database_name,
                query_count=query_count,
                user_count=user_count,
                last_accessed=access_ts,
                source="pdcr",
                source_json={
                    # Stash the raw PDCR row for traceability.
                    "platform_name": r.platform_name,
                    "object_num": r.object_num,
                    "object_type_pdcr": r.object_type,
                    "freq_of_use": r.freq_of_use,
                    "type_of_use": r.type_of_use,
                    "target_indicator": r.target_indicator,
                    "query_count": r.query_count,
                    "distinct_user_count": r.distinct_user_count,
                },
            )
        )
        result.inserted += 1

    session.flush()
    _logger.info(
        "persist_object_usage: inserted=%d skipped_unmapped=%d skipped_orphan=%d "
        "skipped_invalid=%d (skipped_by_type=%s)",
        result.inserted,
        result.skipped_unmapped_type,
        result.skipped_orphan,
        result.skipped_invalid,
        dict(sorted(result.skipped_by_type.items())),
    )
    return result


# ──── Case-insensitive graph index ────

def build_node_index(
    snapshot_id: int,
    session: Session,
) -> dict[tuple[str, str], int]:
    """Return a case-insensitive (schema, name) → node_id map.

    Loads all ``graph_node`` rows for the given snapshot into memory
    (typically 240k rows for Transcend, ~30 MB Python dict) and keys
    them by lowercased ``(schema_name, object_name)``. The dict is
    discarded after the batch, so memory is reclaimed cleanly.

    Returning a dict (not a query function) is intentional: per-row
    lookups against 240k rows would issue 240k SQL queries against
    the same indexed columns. Materialise once, lookup in memory.
    """
    rows = session.execute(
        select(
            GraphNode.schema_name,
            GraphNode.object_name,
            GraphNode.node_id,
        ).where(GraphNode.snapshot_id == snapshot_id)
    ).all()
    # graph_builder stores object_name as "schema.table" (qualified); PDCR
    # looks up by bare table_name — strip the schema prefix so keys match.
    result: dict[tuple[str, str], int] = {}
    for s, n, nid in rows:
        bare = n.split(".", 1)[1] if "." in n else n
        result[(s.lower(), bare.lower())] = nid
    return result


# ──── Helpers ────

def _parse_timestamp(s: str) -> Optional[datetime]:
    """Parse PDCR's `"2026-05-12 17:47:57.646670"` style timestamp.

    Returns ``None`` for empty / unparseable values so the caller can
    count them as ``skipped_invalid`` rather than raising. PDCR's
    contract says these are always populated; this is defensive.
    """
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    # PDCR uses `YYYY-MM-DD HH:MM:SS.ffffff` (microsecond precision)
    # without a timezone. Teradata native timezone is implicit; we
    # store as naive (no tz attached) for consistency with how
    # `usage_event.last_accessed` already works.
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _parse_date(s: str) -> Optional[datetime]:
    """Parse PDCR's `"2026/05/12"` style date (or fall through formats)."""
    if not s:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None
