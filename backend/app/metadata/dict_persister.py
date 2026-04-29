from __future__ import annotations

"""Persist a validated data-dictionary batch as a SCION snapshot.

Input: 6 lists of dataclass records (databases, tables, columns,
indices, partitioning, tabletext) that have already been parsed by
`dict_flat_file_reader` and consistency-checked by
`dict_batch_validator`.

Output: one new row in `snapshot` plus the corresponding rows in
`schema_snapshot` / `table_snapshot` / `column_snapshot`. Indices,
partitioning and tabletext are summarised in the description for now —
they're useful but don't fit the existing 3-table snapshot schema, and
adding tables for them is a Phase-2 migration we defer until the graph
side actually consumes them.

Idempotency: an `extract_run_id` is unique per Rahul's orchestration
run, so re-importing the same batch should be a no-op (we detect by
looking at `snapshot.description`, which embeds the run_id). The
caller can override with `force=True` to create a duplicate snapshot
for testing.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot

from .teradata_type_formatter import (
    format_column_type, is_nullable, object_type_from_tablekind,
    ColumnTypeInput,
)
from .dict_flat_file_reader import (
    DatabaseRecord, TableRecord, ColumnRecord, IndexRecord,
    PartitioningRecord, TableTextRecord,
)
from .dict_batch_validator import BatchIdentity


# ──── Result type ────

@dataclass(frozen=True)
class PersistResult:
    """What was created (or skipped). Returned to the route handler so
    the response body can include human-readable counts without the
    handler having to query back."""
    snapshot_id: int
    schemas_created: int
    tables_created: int
    columns_created: int
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

    return PersistResult(
        snapshot_id=snap.snapshot_id,
        schemas_created=len(schema_id_by_name),
        tables_created=len(table_id_by_qname),
        columns_created=columns_created,
        indices_seen=len(indices),
        partitioning_seen=len(partitioning),
        tabletext_seen=len(tabletext),
        skipped_existing=False,
        identity=identity,
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
