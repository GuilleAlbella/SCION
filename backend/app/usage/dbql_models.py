"""ORM model for the reassembled DBQL query log (Pipeline 3, PR-C).

The `dbql_query` table stores one row per *reconstructed* SQL query
ingested from a `pdcr_log_*.dat` file. PDCR delivers SQL in
fragments — one row per (QueryID, SqlRowNo) — and the reader
(`pdcr_flat_file_reader.reassemble_query`) joins those back into the
full statement before the persister writes here. So one row in this
table = one SQL statement that ran on the warehouse.

Why a separate table (and not `usage_event`)
============================================

`usage_event` is a counter shape: object × time-window → counts.
`dbql_query` is a record shape: query_id → full SQL text + metadata.
They answer different questions ("how often is X used?" vs "what
did query 12345 actually do?") and conflating them would force
either bloated rows or duplicate keys.

The DataDNA correlation case is the prime driver for keeping the
full text: Rahul's team needs to map QueryID to the lineage their
parser extracted, and that's only possible when we still have the
exact bytes that Teradata logged.

Snapshot independence
=====================

DBQL is **operational**, not structural. A query that ran at
2026-05-12 10:00 doesn't belong to "the snapshot taken at
2026-05-12 09:00" any more than a thermometer reading belongs to
yesterday's calendar entry. So this table has no `snapshot_id` —
it's a global log keyed by `(query_id, collect_timestamp)`.

When the criticality engine (PR-E) re-computes per-snapshot
criticality from DBQL, it joins by name and date range, not by FK.
"""

from __future__ import annotations

from datetime import UTC, date as date_type, datetime
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DBQLQuery(Base):
    """One reassembled SQL query from a PDCR DBQL extract.

    A complete query is the concatenation of all `pdcr_log` records
    that share a QueryID, sorted by SqlRowNo. The fragment-level data
    is intentionally not persisted: anyone who needs to debug the
    fragmentation can re-parse the source `.dat` file with
    `pdcr_flat_file_reader.read_dbql_log`.
    """

    __tablename__ = "dbql_query"

    dbql_query_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    # PDCR QueryID is a 64-bit identifier (Teradata uses bigint here).
    # Store as BigInteger so we don't truncate on SQLite — SQLite
    # treats `Integer` as a flexible affinity but other dialects need
    # the explicit BigInteger. Cheap insurance for the v1.25 Postgres
    # migration.
    query_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # When this query was logged. `collect_timestamp` is the exact
    # moment Teradata emitted the log row; `log_date` is the calendar
    # day Rahul's extractor partitions by (so queries from one window
    # can be loaded efficiently).
    collect_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    log_date: Mapped[date_type] = mapped_column(Date, nullable=False)

    # PE/AMP process id — not strictly needed by SCION but kept for
    # operator diagnostics ("which PE handled this query?") and for
    # DataDNA correlation (the parser emits ProcID-aware lineage).
    proc_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # The reassembled SQL. Can be long (multi-line CTEs, complex MERGE
    # statements) but typically under 10 KB. `Text` so dialects with
    # row-length limits don't truncate.
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Resolution hint from the producer: which database to assume for
    # unqualified table references in `sql_text`. Used by DataDNA
    # downstream.
    default_database: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # QueryBand attribution — job/proc that ran the SQL. Often null
    # (ad-hoc queries don't carry QueryBand). Useful for grouping
    # queries by ETL flow.
    qb_job_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    qb_proc_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Source system label, e.g. "Transcend-DevTest". Multi-customer
    # deploys would key by this; v1.x is single-tenant so it's
    # informational.
    platform_name: Mapped[str] = mapped_column(String, nullable=False)

    # When SCION ingested this — distinct from `collect_timestamp`
    # which is when Teradata logged it. Lets operators see "you have
    # DBQL data up to {max(ingested_at)}".
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # ────────────────────────────────────────────────────────────────
    # Idempotency: re-ingesting the same `pdcr_log` file must NOT
    # produce duplicate rows. The natural key is the pair
    # (QueryID, CollectTimeStamp) because in theory the same QueryID
    # could appear with different timestamps across separate extract
    # windows (Teradata reuses QueryIDs after a procid rollover, but
    # not within the same collect_timestamp).
    #
    # Indexes:
    #   - (query_id) — DataDNA correlation lookup is keyed by it.
    #   - (log_date) — operator queries ("what ran on 2026-05-12?")
    #   - (default_database, log_date) — "usage by db, by day"
    # ────────────────────────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint(
            "query_id",
            "collect_timestamp",
            name="uq_dbql_query_id_collect_ts",
        ),
        Index("ix_dbql_query_id", "query_id"),
        Index("ix_dbql_query_log_date", "log_date"),
        Index(
            "ix_dbql_query_db_date",
            "default_database",
            "log_date",
        ),
    )
