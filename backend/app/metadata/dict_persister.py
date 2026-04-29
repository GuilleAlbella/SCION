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
from typing import List, Optional, Tuple

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


logger = logging.getLogger(__name__)


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
    columns: List[ColumnRecord],
    indices: List[IndexRecord],
    partitioning: List[PartitioningRecord],
    tabletext: List[TableTextRecord],
    force: bool = False,
) -> PersistResult:
    """Persist one extraction run as one SCION snapshot.

    Args:
        session: open SQLAlchemy session; caller owns commit/rollback.
        identity: validated by `dict_batch_validator.validate_batch`.
        databases/tables/columns/...: parsed records from each file.
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
            return PersistResult(
                snapshot_id=existing.snapshot_id,
                schemas_created=0,
                tables_created=0,
                columns_created=0,
                indices_created=0,
                partitioning_created=0,
                ddl_text_created=0,
                indices_seen=len(indices),
                partitioning_seen=len(partitioning),
                tabletext_seen=len(tabletext),
                skipped_existing=True,
                identity=identity,
            )

    # ──── Snapshot row ────
    snap = Snapshot(
        snapshot_time=datetime.utcnow(),
        source_system=identity.source_system_name,
        description=_build_description(
            identity, databases, tables, columns,
            indices, partitioning, tabletext,
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
    schema_names: set[str] = set()
    schema_names.update(d.database_name for d in databases if d.database_name)
    schema_names.update(t.database_name for t in tables if t.database_name)
    schema_id_by_name: dict[str, int] = {}
    for name in sorted(schema_names):
        s = SchemaSnapshot(snapshot_id=snap.snapshot_id, schema_name=name)
        session.add(s)
        session.flush()
        schema_id_by_name[name] = s.schema_id

    # ──── Table rows ────
    # Key by (database_name, table_name) so the column loop can FK to
    # the right table_id. TableKind → object_type via the existing
    # mapper so the graph engine consumes the same enum it already does.
    table_id_by_qname: dict[Tuple[str, str], int] = {}
    for t in tables:
        schema_id = schema_id_by_name.get(t.database_name)
        if schema_id is None:
            # Should not happen given the schema_names superset above,
            # but guard defensively — corrupt data shouldn't crash the
            # whole ingest, just skip the row and let the description
            # surface the discrepancy if it gets weird.
            continue
        ts = TableSnapshot(
            schema_id=schema_id,
            table_name=t.table_name,
            object_type=object_type_from_tablekind(t.table_kind),
        )
        session.add(ts)
        session.flush()
        table_id_by_qname[(t.database_name, t.table_name)] = ts.table_id

    # ──── Column rows ────
    columns_created = 0
    for c in columns:
        table_id = table_id_by_qname.get((c.database_name, c.table_name))
        if table_id is None:
            # Column referencing a table we didn't ingest. Common for
            # views over system tables; safe to skip with a count for
            # diagnostics rather than abort.
            continue
        try:
            data_type = format_column_type(_column_type_input(c))
        except Exception:
            # Don't let one weird type code abort the whole ingest.
            data_type = c.column_type or "UNKNOWN"
        cs = ColumnSnapshot(
            table_id=table_id,
            column_name=c.column_name,
            data_type=data_type,
            nullable=is_nullable(c.nullable),
            ordinal_position=c.column_id or 0,
        )
        session.add(cs)
        columns_created += 1

    # ──── Index rows (v1.14.02) ────
    # One row per (index, column) pair, mirroring DBC.IndicesV. Skip
    # any record whose target table isn't in our snapshot — same
    # philosophy as columns: drop silently with a counter, don't abort.
    indices_created = 0
    for idx in indices:
        table_id = table_id_by_qname.get((idx.database_name, idx.table_name))
        if table_id is None:
            continue
        session.add(IndexSnapshot(
            table_id=table_id,
            index_name=idx.index_name,
            index_number=idx.index_number,
            index_type=idx.index_type,
            unique_flag=idx.unique_flag,
            column_name=idx.column_name,
            column_position=idx.column_position,
        ))
        indices_created += 1

    # ──── Partitioning rows (v1.14.02) ────
    # One row per partitioning constraint. ConstraintText stored
    # verbatim — see model docstring for why we don't parse it.
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

    # ──── DDL text rows (v1.14.02) ────
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

    return PersistResult(
        snapshot_id=snap.snapshot_id,
        schemas_created=len(schema_id_by_name),
        tables_created=len(table_id_by_qname),
        columns_created=columns_created,
        indices_created=indices_created,
        partitioning_created=partitioning_created,
        ddl_text_created=ddl_text_created,
        indices_seen=len(indices),
        partitioning_seen=len(partitioning),
        tabletext_seen=len(tabletext),
        skipped_existing=False,
        identity=identity,
    )


def run_post_ingest_pipeline(snapshot_id: int) -> None:
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

    # Step 1+2: structural hash + snapshot metrics.
    # `compute_structural_hash` returns the hash; we persist it on the
    # snapshot row so the diff engine can short-circuit identical
    # snapshots without re-walking everything.
    try:
        h = compute_structural_hash(snapshot_id)
        with ORMSession(bind=engine) as sess:
            snap = sess.get(Snapshot, snapshot_id)
            if snap is not None:
                snap.structural_hash = h
                sess.commit()
    except Exception as e:
        logger.warning("post-ingest: structural_hash failed for %s: %s", snapshot_id, e)

    try:
        compute_snapshot_metrics(snapshot_id)
    except Exception as e:
        logger.warning("post-ingest: snapshot_metrics failed for %s: %s", snapshot_id, e)

    # Step 3+4: build the technical graph and node metrics.
    # The FK heuristic in build_graph_for_snapshot looks for column
    # naming conventions (`*_id`, `id`) to infer FEEDS edges. Dict
    # snapshots have column names but no explicit FK metadata, so
    # edges may be sparse. That's fine — nodes alone unblock /graph
    # and /lineage.
    try:
        build_graph_for_snapshot(snapshot_id)
    except Exception as e:
        logger.warning("post-ingest: build_graph failed for %s: %s", snapshot_id, e)

    try:
        persist_node_metrics(snapshot_id)
    except Exception as e:
        logger.warning("post-ingest: persist_node_metrics failed for %s: %s", snapshot_id, e)

    # Step 5: criticality (graph-only fallback).
    # `usage_available=False` switches off the usage-aggregation branch
    # so we don't need a usage feed to populate /usage and
    # /intelligence. The combined score becomes the graph score alone;
    # HIGH/MEDIUM/LOW thresholds stay at 0.6 / 0.3 (so banding looks
    # consistent across snapshots that do or don't have usage data).
    try:
        compute_criticality(snapshot_id, usage_available=False)
    except Exception as e:
        logger.warning("post-ingest: compute_criticality failed for %s: %s", snapshot_id, e)

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
    try:
        _auto_diff_against_previous(snapshot_id)
    except Exception as e:
        logger.warning("post-ingest: auto-diff failed for %s: %s", snapshot_id, e)


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
    columns: List[ColumnRecord],
    indices: List[IndexRecord],
    partitioning: List[PartitioningRecord],
    tabletext: List[TableTextRecord],
) -> str:
    """Stuff metadata into `snapshot.description`.

    Two purposes:
      1. **Idempotency lookup** — `extract_run_id=...` is a stable
         substring we can grep for to detect re-imports.
      2. **Human inspection** — counts surfaced in the Sidebar /
         snapshot list without having to drill into each table.

    Format kept stable across releases because the idempotency check
    uses LIKE matching on it. Don't reorder without thinking about
    backward compatibility.
    """
    return (
        f"Data dictionary import | "
        f"source={identity.source_system_name} | "
        f"extract_run_id={identity.extract_run_id} | "
        f"databases={len(databases)} | "
        f"tables={len(tables)} | "
        f"columns={len(columns)} | "
        f"indices={len(indices)} | "
        f"partitioning={len(partitioning)} | "
        f"tabletext_fragments={len(tabletext)}"
    )
