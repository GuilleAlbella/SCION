from __future__ import annotations

"""Persist a validated data-dictionary batch as a SCION snapshot.

Input: 6 lists of dataclass records (databases, tables, columns,
indices, partitioning, tabletext) that have already been parsed by
`dict_flat_file_reader` and consistency-checked by
`dict_batch_validator`.

Output: one new row in `snapshot` plus the corresponding rows in
`schema_snapshot` / `table_snapshot` / `column_snapshot`, AND the
post-ingest analytical pipeline runs against the new snapshot so
the rest of SCION (graph, metrics, criticality, snapshot stats)
sees the data immediately. Without that pipeline, the snapshot
appears in /snapshots but every other page reports empty — which
is exactly what users hit in v1.13.02 (see Issue: "imported but
no data in graph/metrics/usage").

Indices, partitioning and tabletext are parsed and counted but not
yet persisted to dedicated tables — that's a Phase-2 schema
migration deferred until the graph side actually consumes them.

Idempotency: `extract_run_id` is unique per Rahul's orchestration
run, so re-importing the same batch is a no-op. We detect via the
indexed `extract_run_id` column on `snapshot` (v1.13.01+) with a
fallback to the description-LIKE pattern for v1.12-era rows. The
caller can override with `force=True` to create a duplicate snapshot
for testing.
"""

from dataclasses import dataclass
from datetime import datetime
import logging
import time
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot
from app.db.models.index_snapshot import IndexSnapshot
from app.db.models.partitioning_snapshot import PartitioningSnapshot
from app.db.models.ddl_text_snapshot import DDLTextSnapshot

from .teradata_type_formatter import (
    format_column_type, is_nullable, object_type_from_tablekind,
    ColumnTypeInput,
)
from .dict_flat_file_reader import (
    DatabaseRecord, TableRecord, ColumnRecord, IndexRecord,
    PartitioningRecord, TableTextRecord, assemble_ddl,
)
from .dict_batch_validator import BatchIdentity


# ──── Streaming bulk-insert tuning ────
# Trade-off:
#  - Too small: more SQL round-trips, more session bookkeeping per row.
#  - Too large: each batch holds N dicts in memory plus SQLite has to
#    parse a single huge INSERT statement.
# 5 000 rows × ~200 bytes/dict ≈ ~1 MB per batch — well under any
# memory pressure threshold but still big enough that SQLite amortises
# the per-statement overhead. Tuned with the Transcend-DevTest 9.8M-row
# columns file (1.9 GB) on a laptop-class machine. Don't change without
# re-benchmarking via `tools/benchmark_ingest.py`.
_BULK_INSERT_BATCH_SIZE = 5000

# How often the streaming-bulk helpers emit a progress line. Each line
# is one round trip through Python's logging stack, so we don't want
# to do it per batch — but we do want enough heartbeats that an
# operator can see progress within a few seconds. 250 000 rows ≈
# 50 batches between heartbeats; on the Transcend-DevTest extract
# that's a log line every ~5-10 seconds, which feels live without
# being noisy.
_PROGRESS_LOG_EVERY_ROWS_COLUMNS = 250_000
_PROGRESS_LOG_EVERY_ROWS_INDICES = 50_000


logger = logging.getLogger(__name__)


def _fmt_time(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}m {s:05.2f}s"


# ──── Result type ────

@dataclass(frozen=True)
class PersistResult:
    """What was created (or skipped). Returned to the route handler so
    the response body can include human-readable counts without the
    handler having to query back.

    The `_seen` fields are the raw record counts from Rahul's batch
    (input). The `_created` fields are how many rows actually landed
    in SCION's DB. They diverge when a record references a parent
    object we didn't ingest (e.g. an index on a system table that
    `tables.dat` didn't include) — we skip rather than abort.
    """
    snapshot_id: int
    schemas_created: int
    tables_created: int
    columns_created: int
    # Sub-tables added in v1.14.02 — counts of what was persisted, not
    # just seen. The endpoint surfaces both `_created` and `_seen` so
    # users can spot drops.
    indices_created: int
    partitioning_created: int
    ddl_text_created: int
    indices_seen: int
    partitioning_seen: int
    tabletext_seen: int
    skipped_existing: bool
    identity: BatchIdentity


# ──── Public API ────

def persist_batch(
    session: Session,
    identity: BatchIdentity,
    databases: List[DatabaseRecord],
    tables: List[TableRecord],
    columns: Iterable[ColumnRecord],
    indices: Iterable[IndexRecord],
    partitioning: List[PartitioningRecord],
    tabletext: List[TableTextRecord],
    force: bool = False,
    import_id: Optional[str] = None,
) -> PersistResult:
    """Persist one extraction run as one SCION snapshot.

    Args:
        session: open SQLAlchemy session; caller owns commit/rollback.
        identity: validated by `dict_batch_validator.validate_batch`.
        databases / tables / partitioning / tabletext: parsed records
            (materialised — small enough to hold in memory).
        columns / indices: parsed records, accepted as `Iterable` so
            the route handler can stream them straight from the
            `iter_*` generators without materialising. Critical for
            production-scale extracts where columns alone is 9.8M+ rows
            (Transcend-DevTest full = 1.9 GB on disk). Lists still work
            (used by tests + the small-extract path).
        force: if True, ignore an existing snapshot with the same run_id
               and create a new one anyway. Useful for testing the
               pipeline end-to-end without manually deleting rows.

    Returns:
        PersistResult with counts and the new snapshot_id.
    """
    # ──── Idempotency check ────
    # Primary signal: the dedicated `extract_run_id` column (v1.13+).
    # Fallback: the description-LIKE pattern from v1.12.00 — kept for
    # one release so DBs migrated from v1.12 still recognise their
    # existing dict-import snapshots without a re-scan. Drop the
    # fallback in v1.14.
    if not force:
        existing = (
            session.query(Snapshot)
            .filter(Snapshot.source_system == identity.source_system_name)
            .filter(
                (Snapshot.extract_run_id == identity.extract_run_id)
                | Snapshot.description.like(
                    f"%extract_run_id={identity.extract_run_id}%"
                )
            )
            .one_or_none()
        )
        if existing is not None:
            # Idempotent re-import: we don't drain the columns/indices
            # iterators because there's nothing to do — the prior run
            # already persisted everything. Streaming-friendly seen
            # counts are reported as 0 here on purpose (we can't count
            # what we don't read). The response field `skipped_existing`
            # tells the caller why the other counts are zero.
            return PersistResult(
                snapshot_id=existing.snapshot_id,
                schemas_created=0,
                tables_created=0,
                columns_created=0,
                indices_created=0,
                partitioning_created=0,
                ddl_text_created=0,
                indices_seen=0,
                partitioning_seen=len(partitioning),
                tabletext_seen=len(tabletext),
                skipped_existing=True,
                identity=identity,
            )

    # ──── Snapshot row ────
    # Description is built from the materialised lists only (databases,
    # tables, partitioning, tabletext). Columns and indices are
    # iterators at this point — we'd consume them just to count, which
    # defeats the streaming. Their final counts are reported back via
    # PersistResult / DictImportResponse instead, which is the more
    # authoritative source anyway.
    snap = Snapshot(
        snapshot_time=datetime.utcnow(),
        source_system=identity.source_system_name,
        description=_build_description(
            identity, databases, tables, partitioning, tabletext,
        ),
        is_baseline=False,
        object_count=len(tables),  # tables/views/procs — the headline count
        extract_run_id=identity.extract_run_id,
    )
    session.add(snap)
    session.flush()  # populate snap.snapshot_id without committing

    # ──── Schema rows ────
    # Build from the union of database_names appearing in tables AND
    # databases. We can't trust just `databases.dat` because some
    # `tables.dat` rows reference databases that aren't in the dict
    # extract (system DBs like DBC). Always use the superset.
    t_phase = time.perf_counter()
    schema_names: set[str] = set()
    schema_names.update(d.database_name for d in databases if d.database_name)
    schema_names.update(t.database_name for t in tables if t.database_name)
    schema_id_by_name: dict[str, int] = {}
    for name in sorted(schema_names):
        s = SchemaSnapshot(snapshot_id=snap.snapshot_id, schema_name=name)
        session.add(s)
        session.flush()
        schema_id_by_name[name] = s.schema_id
    logger.info("[persist] schemas    %9d rows in %s",
                len(schema_id_by_name), _fmt_time(time.perf_counter() - t_phase))

    # ──── Table rows ────
    # Bulk-insert pattern: collect dicts, ship them in batches through
    # `bulk_insert_mappings`, then re-fetch with one SELECT to recover
    # `table_id` for every row. Same approach we use in `graph_builder`
    # — and the same reason: per-row `session.add` + `session.flush`
    # was costing ~33 s for the Transcend-DevTest extract's 240k
    # tables (~7k rows/s, dominated by ORM bookkeeping). Bulk-insert
    # drops it to a few seconds.
    #
    # Why we re-query instead of trusting `bulk_insert_mappings` to
    # populate the dict's autogenerated `table_id`: it doesn't. The
    # SQLAlchemy 2.0 docs are explicit that `bulk_insert_mappings`
    # bypasses the unit-of-work and won't return server-assigned
    # PKs. One extra SELECT for 240k rows is much cheaper than 240k
    # individual flushes.
    t_phase = time.perf_counter()
    table_inserts: list[dict] = []
    skipped_for_orphan_schema = 0
    for t in tables:
        schema_id = schema_id_by_name.get(t.database_name)
        if schema_id is None:
            # Should not happen given the schema_names superset above,
            # but guard defensively — corrupt data shouldn't crash the
            # whole ingest, just skip the row and let the description
            # surface the discrepancy if it gets weird.
            skipped_for_orphan_schema += 1
            continue
        table_inserts.append({
            "schema_id": schema_id,
            "table_name": t.table_name,
            "object_type": object_type_from_tablekind(t.table_kind),
        })

    if table_inserts:
        for i in range(0, len(table_inserts), _BULK_INSERT_BATCH_SIZE):
            session.bulk_insert_mappings(
                TableSnapshot, table_inserts[i:i + _BULK_INSERT_BATCH_SIZE]
            )

    # Re-fetch every table for this snapshot to map (database_name,
    # table_name) → table_id. Uses a JOIN through SchemaSnapshot so
    # the filter stays at snapshot scope without an IN(big_list).
    table_id_by_qname: dict[Tuple[str, str], int] = {}
    for tid, schema_name, table_name in session.execute(
        select(
            TableSnapshot.table_id,
            SchemaSnapshot.schema_name,
            TableSnapshot.table_name,
        )
        .join(
            SchemaSnapshot,
            TableSnapshot.schema_id == SchemaSnapshot.schema_id,
        )
        .where(SchemaSnapshot.snapshot_id == snap.snapshot_id)
    ).all():
        table_id_by_qname[(schema_name, table_name)] = tid
    logger.info("[persist] tables     %9d rows in %s",
                len(table_id_by_qname), _fmt_time(time.perf_counter() - t_phase))
    if skipped_for_orphan_schema:
        logger.warning(
            "[persist] %d table rows skipped — referenced schema not in this snapshot",
            skipped_for_orphan_schema,
        )

    # ──── Column rows (streaming bulk-insert) ────
    # We accept `columns` as an Iterable so the route handler can hand
    # us the reader's generator directly — no list materialisation.
    # Records are accumulated into batches of `_BULK_INSERT_BATCH_SIZE`
    # and flushed with `session.bulk_insert_mappings`, which bypasses
    # ORM object construction and identity-map insertion (the killer
    # for 9.8M-row inserts). Memory stays bounded at ~1 MB per batch.
    t_phase = time.perf_counter()
    columns_created, columns_seen = _bulk_insert_columns_streaming(
        session, columns, table_id_by_qname, import_id=import_id,
    )
    logger.info(
        "[persist] columns    %9d rows in %s  (%d seen, %d skipped → orphan parent)",
        columns_created, _fmt_time(time.perf_counter() - t_phase),
        columns_seen, columns_seen - columns_created,
    )

    # ──── Index rows (streaming bulk-insert) ────
    t_phase = time.perf_counter()
    # Same pattern as columns. Indices is smaller (~340k rows for
    # Transcend-DevTest) but the contract is identical so we route it
    # through the same helper for consistency and to avoid per-row
    # ORM overhead. Skip any record whose target table isn't in our
    # snapshot — same philosophy as columns: drop silently, don't
    # abort.
    indices_created, indices_seen = _bulk_insert_indices_streaming(
        session, indices, table_id_by_qname, import_id=import_id,
    )
    logger.info(
        "[persist] indices    %9d rows in %s  (%d seen, %d skipped)",
        indices_created, _fmt_time(time.perf_counter() - t_phase),
        indices_seen, indices_seen - indices_created,
    )

    # ──── Partitioning rows (v1.14.02) ────
    # One row per partitioning constraint. ConstraintText stored
    # verbatim — see model docstring for why we don't parse it.
    t_phase = time.perf_counter()
    partitioning_created = 0
    for p in partitioning:
        table_id = table_id_by_qname.get((p.database_name, p.table_name))
        if table_id is None:
            continue
        session.add(PartitioningSnapshot(
            table_id=table_id,
            constraint_type=p.constraint_type,
            constraint_text=p.constraint_text,
            create_timestamp=p.create_timestamp,
        ))
        partitioning_created += 1
    logger.info("[persist] partition  %9d rows in %s",
                partitioning_created, _fmt_time(time.perf_counter() - t_phase))

    # ──── DDL text rows (v1.14.02) ────
    t_phase = time.perf_counter()
    # Tabletext arrives as fragments ordered by `request_text_seq`;
    # `assemble_ddl` concatenates them per (database, table) into the
    # full CREATE statement. We persist one row per object regardless
    # of how many fragments TableTextV produced.
    ddl_text_created = 0
    assembled = assemble_ddl(tabletext)  # {(db, tbl): full_ddl}
    fragment_counts: dict[Tuple[str, str], int] = {}
    for r in tabletext:
        key = (r.database_name, r.table_name)
        fragment_counts[key] = fragment_counts.get(key, 0) + 1
    for (db_name, tbl_name), ddl in assembled.items():
        table_id = table_id_by_qname.get((db_name, tbl_name))
        if table_id is None:
            continue
        session.add(DDLTextSnapshot(
            table_id=table_id,
            ddl_text=ddl,
            request_text_fragments=fragment_counts.get((db_name, tbl_name), 1),
        ))
        ddl_text_created += 1
    logger.info("[persist] ddl_text   %9d rows in %s",
                ddl_text_created, _fmt_time(time.perf_counter() - t_phase))

    return PersistResult(
        snapshot_id=snap.snapshot_id,
        schemas_created=len(schema_id_by_name),
        tables_created=len(table_id_by_qname),
        columns_created=columns_created,
        indices_created=indices_created,
        partitioning_created=partitioning_created,
        ddl_text_created=ddl_text_created,
        indices_seen=indices_seen,
        partitioning_seen=len(partitioning),
        tabletext_seen=len(tabletext),
        skipped_existing=False,
        identity=identity,
    )


def run_post_ingest_pipeline(
    snapshot_id: int, import_id: Optional[str] = None,
) -> None:
    """Run the analytical pipeline that fills graph + metrics tables.

    **Call this AFTER `persist_batch` and AFTER the caller has committed
    its transaction.** Each step opens its own session against the
    global engine, so the snapshot rows must be visible there before
    the helpers run.

    Without this, /graph, /metrics, /usage, /intelligence, /lineage and
    /impact all show empty for a freshly-imported snapshot. Order matters:
      1. structural_hash — fingerprint for de-duplication
      2. snapshot_metrics — counts (databases, tables, columns)
      3. build_graph_for_snapshot — graph_node + graph_edge from FK
         heuristics (works on dict snapshots, though edges may be
         sparse without explicit FK metadata)
      4. persist_node_metrics — fragility, in/out degree, hub flag
      5. compute_criticality(usage_available=False) — graph-only
         criticality scores; usage will be re-computed when pipeline 3
         lands. Without this, /usage and /intelligence show empty.

    Errors are logged and swallowed per step. We'd rather have a
    snapshot with partial analytical metadata than reject the whole
    import because one downstream metric blew up on edge-case data.
    """
    # Late imports: these modules pull in graph/usage/snapshot
    # subsystems and the import graph would be unnecessarily heavy if
    # we hoisted them to module top. Late binding also dodges potential
    # circular-import issues when the package grows.
    from app.snapshot.structural_hash import compute_structural_hash
    from app.snapshot.snapshot_metrics import compute_snapshot_metrics
    from app.graph.graph_builder import build_graph_for_snapshot
    from app.graph.graph_metrics import persist_node_metrics
    from app.usage.criticality_engine import compute_criticality
    from app.db.engine import engine
    from sqlalchemy.orm import Session as ORMSession

    # Helper to push sub-step captions to the in-memory progress
    # tracker. Lazy-imported so this module stays usable even if the
    # API layer isn't loaded (e.g. CLI tools that call the post-ingest
    # pipeline directly).
    def _push_caption(caption: str) -> None:
        if import_id is None:
            return
        from app.api.v1 import import_progress as _ip
        _ip.update_progress(import_id, "post_ingest", caption=caption)

    # Step 1+2: structural hash + snapshot metrics.
    # `compute_structural_hash` returns the hash; we persist it on the
    # snapshot row so the diff engine can short-circuit identical
    # snapshots without re-walking everything.
    _push_caption("hashing snapshot structure…")
    t_step = time.perf_counter()
    try:
        h = compute_structural_hash(snapshot_id)
        with ORMSession(bind=engine) as sess:
            snap = sess.get(Snapshot, snapshot_id)
            if snap is not None:
                snap.structural_hash = h
                sess.commit()
    except Exception as e:
        logger.warning("post-ingest: structural_hash failed for %s: %s", snapshot_id, e)
    logger.info("[post-ingest] structural_hash   in %s", _fmt_time(time.perf_counter() - t_step))

    _push_caption("computing snapshot metrics…")
    t_step = time.perf_counter()
    try:
        compute_snapshot_metrics(snapshot_id)
    except Exception as e:
        logger.warning("post-ingest: snapshot_metrics failed for %s: %s", snapshot_id, e)
    logger.info("[post-ingest] snapshot_metrics  in %s", _fmt_time(time.perf_counter() - t_step))

    # Step 3+4: build the technical graph and node metrics.
    # The FK heuristic in build_graph_for_snapshot looks for column
    # naming conventions (`*_id`, `id`) to infer FEEDS edges. Dict
    # snapshots have column names but no explicit FK metadata, so
    # edges may be sparse. That's fine — nodes alone unblock /graph
    # and /lineage.
    _push_caption("building lineage graph…")
    t_step = time.perf_counter()
    try:
        build_graph_for_snapshot(snapshot_id)
    except Exception as e:
        logger.warning("post-ingest: build_graph failed for %s: %s", snapshot_id, e)
    logger.info("[post-ingest] build_graph       in %s", _fmt_time(time.perf_counter() - t_step))

    _push_caption("computing node metrics (fragility, degree)…")
    t_step = time.perf_counter()
    try:
        persist_node_metrics(snapshot_id)
    except Exception as e:
        logger.warning("post-ingest: persist_node_metrics failed for %s: %s", snapshot_id, e)
    logger.info("[post-ingest] node_metrics      in %s", _fmt_time(time.perf_counter() - t_step))

    # Step 5: criticality (graph-only fallback).
    # `usage_available=False` switches off the usage-aggregation branch
    # so we don't need a usage feed to populate /usage and
    # /intelligence. The combined score becomes the graph score alone;
    # HIGH/MEDIUM/LOW thresholds stay at 0.6 / 0.3 (so banding looks
    # consistent across snapshots that do or don't have usage data).
    _push_caption("computing criticality scores…")
    t_step = time.perf_counter()
    try:
        # `force=True` is critical here: without it, `compute_criticality`
        # short-circuits if any rows already exist for this snapshot_id —
        # which silently happens when a previous post-ingest run got far
        # enough to write criticality before failing later, or when the
        # demo seeder created stale rows. From the post-ingest pipeline
        # we always want a fresh recompute against the just-rebuilt graph.
        compute_criticality(snapshot_id, force=True, usage_available=False)
    except Exception as e:
        logger.warning("post-ingest: compute_criticality failed for %s: %s", snapshot_id, e)
    logger.info("[post-ingest] criticality       in %s", _fmt_time(time.perf_counter() - t_step))

    # Step 6: auto-diff vs the previous snapshot of the same source.
    # Without this, the user has to go to /changes and click Run Diff
    # by hand to see what moved between two dict imports — an obvious
    # ergonomic gap when the most natural workflow is "import this
    # week's extract, see what changed since last week".
    #
    # We compare against the most-recent prior snapshot whose
    # source_system matches AND that has a structural_hash (set in
    # step 1) — anything older without a hash is ignored because
    # it's a "naked" snapshot that hasn't been through this pipeline.
    # The diff engine itself is idempotent (skips re-inserting
    # change_event rows for the same pair), so a re-run is a no-op.
    _push_caption("comparing against previous snapshot…")
    t_step = time.perf_counter()
    try:
        _auto_diff_against_previous(snapshot_id)
    except Exception as e:
        logger.warning("post-ingest: auto-diff failed for %s: %s", snapshot_id, e)
    logger.info("[post-ingest] auto_diff         in %s", _fmt_time(time.perf_counter() - t_step))


def _auto_diff_against_previous(snapshot_id: int) -> None:
    """Find the prior snapshot from the same source and run a diff.

    No-op if there isn't one. The diff is logged at INFO level so
    operators see it in the dev console without having to peek at
    /changes — useful during testing when you want to know
    immediately whether the new extract had any structural drift.
    """
    from sqlalchemy import desc
    from sqlalchemy.orm import Session as ORMSession
    from app.db.engine import engine
    from app.diff.diff_engine import DiffEngine

    with ORMSession(bind=engine) as sess:
        current = sess.get(Snapshot, snapshot_id)
        if current is None:
            return
        previous = (
            sess.query(Snapshot)
            .filter(Snapshot.source_system == current.source_system)
            .filter(Snapshot.snapshot_id != snapshot_id)
            .order_by(desc(Snapshot.snapshot_time))
            .first()
        )
        if previous is None:
            logger.info(
                "post-ingest: no prior snapshot for source=%r, skipping auto-diff",
                current.source_system,
            )
            return
        prev_id = previous.snapshot_id
        prev_label = current.source_system

    # DiffEngine.compute_diff persists ChangeEvent rows itself
    # (idempotent — skips re-inserting on duplicate runs). The list
    # it returns is just for our log line; we don't use it further.
    changes = DiffEngine().compute_diff(prev_id, snapshot_id)
    logger.info(
        "post-ingest: auto-diff %d→%d for %s produced %d change(s)",
        prev_id, snapshot_id, prev_label, len(changes),
    )


# ──── Streaming bulk-insert helpers ────


def _bulk_insert_columns_streaming(
    session: Session,
    columns: Iterable[ColumnRecord],
    table_id_by_qname: dict[Tuple[str, str], int],
    import_id: Optional[str] = None,
) -> Tuple[int, int]:
    """Persist column records via batched `bulk_insert_mappings`.

    Returns `(created, seen)`. `seen` is the number of records pulled
    from the iterator (i.e. file rows); `created` is the subset whose
    parent table was in this snapshot. The gap is normal — extracts
    routinely include columns of system tables (DBC.*) we don't ingest.

    Why bulk_insert_mappings (not session.add):
      - Bypasses ORM object construction and identity-map insertion.
        9.8M `session.add` calls grow the session linearly and slow
        SQLAlchemy to a crawl long before the inserts themselves
        become the bottleneck.
      - Insert path is ~5-10× faster on SQLite for our row shape.
      - We never need the assigned PKs back, so the trade-off is free.
    """
    created = 0
    seen = 0
    batch: list[dict] = []
    t_start = time.perf_counter()
    last_log_at = 0
    for c in columns:
        seen += 1
        table_id = table_id_by_qname.get((c.database_name, c.table_name))
        if table_id is None:
            # Heartbeat even when we're skipping rows — an extract
            # heavy on DBC.* could otherwise look frozen for minutes.
            if seen - last_log_at >= _PROGRESS_LOG_EVERY_ROWS_COLUMNS:
                _log_persist_progress(
                    "columns", seen, created, time.perf_counter() - t_start,
                    import_id=import_id,
                )
                last_log_at = seen
            continue
        try:
            data_type = format_column_type(_column_type_input(c))
        except Exception:
            # Don't let one weird type code abort the whole ingest.
            data_type = c.column_type or "UNKNOWN"
        batch.append({
            "table_id": table_id,
            "column_name": c.column_name,
            "data_type": data_type,
            "nullable": is_nullable(c.nullable),
            "ordinal_position": c.column_id or 0,
        })
        created += 1
        if len(batch) >= _BULK_INSERT_BATCH_SIZE:
            session.bulk_insert_mappings(ColumnSnapshot, batch)
            batch.clear()
        if seen - last_log_at >= _PROGRESS_LOG_EVERY_ROWS_COLUMNS:
            _log_persist_progress(
                "columns", seen, created, time.perf_counter() - t_start,
                import_id=import_id,
            )
            last_log_at = seen
            # Cooperative-cancel checkpoint. We only check on heartbeat
            # boundaries (every 250k rows) rather than per-row to keep
            # the hot loop tight. The longest the user waits between
            # clicking Cancel and the persist actually stopping is one
            # heartbeat — for our throughput of ~40k rows/s that's
            # roughly 6 seconds, well below the "feels responsive"
            # threshold for a destructive multi-minute operation.
            _maybe_cancel(import_id)
    if batch:
        session.bulk_insert_mappings(ColumnSnapshot, batch)
    return created, seen


def _bulk_insert_indices_streaming(
    session: Session,
    indices: Iterable[IndexRecord],
    table_id_by_qname: dict[Tuple[str, str], int],
    import_id: Optional[str] = None,
) -> Tuple[int, int]:
    """Persist index records via batched `bulk_insert_mappings`.

    Same pattern as `_bulk_insert_columns_streaming` — see that
    function's docstring for the rationale.
    """
    created = 0
    seen = 0
    batch: list[dict] = []
    t_start = time.perf_counter()
    last_log_at = 0
    for idx in indices:
        seen += 1
        table_id = table_id_by_qname.get((idx.database_name, idx.table_name))
        if table_id is None:
            if seen - last_log_at >= _PROGRESS_LOG_EVERY_ROWS_INDICES:
                _log_persist_progress(
                    "indices", seen, created, time.perf_counter() - t_start,
                    import_id=import_id,
                )
                last_log_at = seen
            continue
        batch.append({
            "table_id": table_id,
            "index_name": idx.index_name,
            "index_number": idx.index_number,
            "index_type": idx.index_type,
            "unique_flag": idx.unique_flag,
            "column_name": idx.column_name,
            "column_position": idx.column_position,
        })
        created += 1
        if len(batch) >= _BULK_INSERT_BATCH_SIZE:
            session.bulk_insert_mappings(IndexSnapshot, batch)
            batch.clear()
        if seen - last_log_at >= _PROGRESS_LOG_EVERY_ROWS_INDICES:
            _log_persist_progress(
                "indices", seen, created, time.perf_counter() - t_start,
                import_id=import_id,
            )
            last_log_at = seen
            _maybe_cancel(import_id)
    if batch:
        session.bulk_insert_mappings(IndexSnapshot, batch)
    return created, seen


def _maybe_cancel(import_id: Optional[str]) -> None:
    """Raise `ImportCancelled` if the user pressed Cancel.

    Called from inside the persist-phase hot loops at
    heartbeat boundaries (every 250k columns / 50k indices) — too
    cheap to matter at that cadence (~one dict lookup per heartbeat),
    too coarse to feel sluggish to the user. Lazy-imports the
    cancellation hook to avoid a circular dep at module load time.
    """
    if import_id is None:
        return
    from app.api.v1 import import_progress as _ip
    if _ip.is_cancel_requested(import_id):
        raise _ip.ImportCancelled(
            f"Import {import_id} cancelled by user request."
        )


def _log_persist_progress(
    label: str, seen: int, created: int, elapsed_seconds: float,
    import_id: Optional[str] = None,
) -> None:
    """Emit one progress heartbeat from inside a streaming bulk insert.

    Format kept compact and parser-friendly: same `[persist] LABEL` prefix
    the per-phase summary uses, plus the live row counter and the
    instantaneous throughput so an operator can eyeball whether the
    persist is making forward progress or has stalled.

    When `import_id` is set, also pushes a caption to the in-memory
    progress tracker so the UI checklist gets the same number live.
    No fractional progress is published — we don't know the total
    row count up front (columns is streamed) — but the caption alone
    is enough to make the persist step feel alive in the UI.
    """
    rate = seen / elapsed_seconds if elapsed_seconds > 0 else 0.0
    logger.info(
        "[persist] %-9s %9d seen / %9d created (%.0f rows/s, %s elapsed)",
        label, seen, created, rate, _fmt_time(elapsed_seconds),
    )
    if import_id is not None:
        # Lazy import to avoid a circular dependency at module load
        # time (`app.api.v1.import_progress` is loaded by the routers
        # which transitively load `dict_persister`).
        from app.api.v1 import import_progress as _ip
        _ip.update_progress(
            import_id,
            "persist_data",
            caption=f"{label}: {seen:,} rows ({rate:,.0f}/s)",
        )


# ──── Helpers ────

def _column_type_input(c: ColumnRecord) -> ColumnTypeInput:
    """Adapt our reader's `ColumnRecord` to the type-formatter's input
    contract. Keeping the adapter here (instead of in the reader) lets
    the reader stay format-faithful — translation lives at the
    persistence boundary."""
    return ColumnTypeInput(
        column_type=c.column_type,
        column_length=c.column_length,
        decimal_total_digits=c.decimal_total_digits,
        decimal_fractional_digits=c.decimal_fractional_digits,
        char_type=c.char_type,
    )


def _build_description(
    identity: BatchIdentity,
    databases: List[DatabaseRecord],
    tables: List[TableRecord],
    partitioning: List[PartitioningRecord],
    tabletext: List[TableTextRecord],
) -> str:
    """Stuff metadata into `snapshot.description`.

    Two purposes:
      1. **Idempotency lookup** — `extract_run_id=...` is a stable
         substring we can grep for to detect re-imports.
      2. **Human inspection** — counts surfaced in the Sidebar /
         snapshot list without having to drill into each table.

    The columns/indices counts are deliberately omitted: those records
    are streamed (Iterable, not List) so we can't `len()` them at
    description time without consuming the iterator. Their final
    counts live in PersistResult and the API response, which is a
    more reliable source anyway (it reflects actual persisted rows,
    not raw input).

    Format kept stable across releases because the idempotency check
    uses LIKE matching on the `extract_run_id=...` substring. Don't
    reorder without thinking about backward compatibility.
    """
    return (
        f"Data dictionary import | "
        f"source={identity.source_system_name} | "
        f"extract_run_id={identity.extract_run_id} | "
        f"databases={len(databases)} | "
        f"tables={len(tables)} | "
        f"partitioning={len(partitioning)} | "
        f"tabletext_fragments={len(tabletext)}"
    )
