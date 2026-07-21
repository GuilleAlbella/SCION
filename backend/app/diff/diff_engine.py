from __future__ import annotations

from typing import Dict, List, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.diff.diff_models import Change, ChangeEvent
from app.diff.diff_rules import (
    REVERSE_CHANGE_TYPE,
    diff_columns,
    diff_schemas,
    diff_tables,
    get_severity,
    is_breaking,
)
from app.db.engine import engine
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot


def _maybe_reverse(changes: List[Change], is_reversed: bool) -> List[Change]:
    """Return *changes* with ADDED↔REMOVED flipped when *is_reversed* is True.

    Symmetric change types (TYPE_CHANGED, NULLABILITY_CHANGED, POSITION_CHANGED)
    are unaffected; only directional ones (ADDED/REMOVED) are inverted.
    before_state and after_state are swapped so callers see consistent data.
    """
    if not is_reversed:
        return changes
    result: List[Change] = []
    for c in changes:
        inv_type = REVERSE_CHANGE_TYPE.get(c.change_type, c.change_type)
        result.append(Change(
            object_type=c.object_type,
            object_identifier=c.object_identifier,
            change_type=inv_type,
            before_state=c.after_state,
            after_state=c.before_state,
            severity=get_severity(inv_type),
            is_breaking=is_breaking(inv_type),
        ))
    return result


class DiffEngine:
    """Structural diff engine orchestrator.

    v5.2 focuses exclusively on schema-level changes:
    - Accepts two snapshot identifiers.
    - Loads schema names from `schema_snapshot` for each snapshot.
    - Computes added and removed schemas.
    - Returns a deterministic, sorted list of `Change` objects.

    No table- or column-level logic, persistence, or advanced rules are
    implemented at this stage.
    """

    def __init__(self) -> None:
        """Initialize a stateless diff engine.

        The engine requires no external dependencies and is safe to construct
        directly from upper layers (API/CLI).
        """

    def compute_diff(self, snapshot_from: int, snapshot_to: int) -> List[Change]:
        """Compute structural differences between two snapshots.

        v5.2 behaviour:
        - Validate that the two snapshot identifiers are not equal.
        - Load schema names for both snapshots.
        - Compute added and removed schemas.

        v5.3 extends this with **table-level** changes only:
        - Loads tables for both snapshots from `table_snapshot` joined to
          `schema_snapshot`.
        - Compares tables by the natural key `(schema_name, table_name)`.
        - Detects TABLE_ADDED, TABLE_REMOVED, and TABLE_TYPE_CHANGED events.
        - Keeps the result deterministic by sorting by
          (object_type, object_identifier, change_type).
        """

        # Guard: diffing a snapshot against itself would always produce an
        # empty result and is almost certainly a caller bug — fail loudly.
        if snapshot_from == snapshot_to:
            raise ValueError("snapshot_from and snapshot_to must be different")

        # ──── Direction normalisation ────
        # Always compute and cache the diff with the lower snapshot_id as
        # "from". This guarantees that compute_diff(A, B) and compute_diff(B, A)
        # return the same count — only the ADDED/REMOVED semantics flip.
        # Without this, two independent cache entries could diverge if the
        # underlying tables changed between the two calls.
        is_reversed = snapshot_from > snapshot_to
        if is_reversed:
            snapshot_from, snapshot_to = snapshot_to, snapshot_from

        # ──── Purge stale reversed-direction cache (migration) ────
        # Earlier versions stored diffs without direction normalisation, so a
        # call with (A>B) would have created a separate cache entry (A, B) that
        # may disagree with the canonical (B, A) entry we use now. Delete any
        # such stale entry so it is never served to callers.
        if is_reversed:
            # At this point snapshot_from/to are already swapped to canonical
            # (lower, higher). The stale entry, if any, has them the other way.
            with Session(engine) as _purge_session:
                stale = (
                    _purge_session.query(ChangeEvent)
                    .filter(
                        ChangeEvent.snapshot_from == snapshot_to,   # original "from"
                        ChangeEvent.snapshot_to == snapshot_from,   # original "to"
                    )
                    .first()
                )
                if stale:
                    _purge_session.query(ChangeEvent).filter(
                        ChangeEvent.snapshot_from == snapshot_to,
                        ChangeEvent.snapshot_to == snapshot_from,
                    ).delete(synchronize_session=False)
                    _purge_session.commit()

        # ──── Idempotency fast-path ────
        # Check for existing change_events BEFORE loading any schema/table/column
        # data. On large snapshots (10M+ columns) the data load takes minutes;
        # returning early here makes repeated calls to compute_diff instant.
        with Session(engine) as _early_session:
            existing_events = (
                _early_session.query(ChangeEvent)
                .filter(
                    ChangeEvent.snapshot_from == snapshot_from,
                    ChangeEvent.snapshot_to == snapshot_to,
                )
                .order_by(
                    ChangeEvent.object_type,
                    ChangeEvent.object_identifier,
                    ChangeEvent.change_type,
                    ChangeEvent.change_id,
                )
                .all()
            )
        if existing_events:
            forward = [
                Change(
                    object_type=e.object_type,
                    object_identifier=e.object_identifier,
                    change_type=e.change_type,
                    before_state=e.before_state,
                    after_state=e.after_state,
                    severity=e.severity or get_severity(e.change_type),
                    is_breaking=e.is_breaking if e.is_breaking is not None else is_breaking(e.change_type),
                )
                for e in existing_events
            ]
            return _maybe_reverse(forward, is_reversed)

        # ──── Step 1: Load raw state from both snapshots ────
        # All reads happen inside a single Session so we get a consistent
        # view of the metadata tables. We intentionally load each level
        # (schema / table / column) into plain Python sets/dicts so the pure
        # rule functions in diff_rules can work without DB access.
        with Session(engine) as session:
            # --- Schema-level diff (v5.2) ---
            # Schemas are compared only by name — a schema is either present
            # or absent; there is no "renamed" detection at this layer.
            schemas_from: Set[str] = set(
                session.scalars(
                    select(SchemaSnapshot.schema_name).where(
                        SchemaSnapshot.snapshot_id == snapshot_from
                    )
                ).all()
            )
            schemas_to: Set[str] = set(
                session.scalars(
                    select(SchemaSnapshot.schema_name).where(
                        SchemaSnapshot.snapshot_id == snapshot_to
                    )
                ).all()
            )

            # --- Table-level diff (v5.3) ---
            # Compare all tables by natural key (schema_name, table_name),
            # regardless of whether the schema exists in both snapshots.
            # We store the object_type (TABLE/VIEW) as the value so we can
            # also detect TABLE_TYPE_CHANGED (e.g. a table morphing into a view).
            tables_from: Dict[Tuple[str, str], str] = {}
            tables_to: Dict[Tuple[str, str], str] = {}

            rows_from = session.execute(
                select(
                    SchemaSnapshot.schema_name,
                    TableSnapshot.table_name,
                    TableSnapshot.object_type,
                )
                .join(
                    TableSnapshot,
                    TableSnapshot.schema_id == SchemaSnapshot.schema_id,
                )
                .where(SchemaSnapshot.snapshot_id == snapshot_from)
            ).all()

            for schema_name, table_name, object_type in rows_from:
                tables_from[(schema_name, table_name)] = object_type

            rows_to = session.execute(
                select(
                    SchemaSnapshot.schema_name,
                    TableSnapshot.table_name,
                    TableSnapshot.object_type,
                )
                .join(
                    TableSnapshot,
                    TableSnapshot.schema_id == SchemaSnapshot.schema_id,
                )
                .where(SchemaSnapshot.snapshot_id == snapshot_to)
            ).all()

            for schema_name, table_name, object_type in rows_to:
                tables_to[(schema_name, table_name)] = object_type

            # --- Column-level diff (v5.4) ---
            # Compare columns only for tables that exist in both snapshots.
            # Rationale: if a table was ADDED/REMOVED, its columns are already
            # implicitly covered by the table-level change, and emitting extra
            # COLUMN_* events would be redundant noise.
            common_tables: Set[Tuple[str, str]] = set(tables_from) & set(
                tables_to
            )

            columns_from: Dict[
                Tuple[str, str, str], Tuple[str, bool, int]
            ] = {}
            columns_to: Dict[
                Tuple[str, str, str], Tuple[str, bool, int]
            ] = {}

            if common_tables:
                col_rows_from = session.execute(
                    select(
                        SchemaSnapshot.schema_name,
                        TableSnapshot.table_name,
                        ColumnSnapshot.column_name,
                        ColumnSnapshot.data_type,
                        ColumnSnapshot.nullable,
                        ColumnSnapshot.ordinal_position,
                    )
                    .join(
                        TableSnapshot,
                        TableSnapshot.schema_id == SchemaSnapshot.schema_id,
                    )
                    .join(
                        ColumnSnapshot,
                        ColumnSnapshot.table_id == TableSnapshot.table_id,
                    )
                    .where(SchemaSnapshot.snapshot_id == snapshot_from)
                ).all()

                for (
                    schema_name,
                    table_name,
                    column_name,
                    data_type,
                    nullable,
                    ordinal_position,
                ) in col_rows_from:
                    key2 = (schema_name, table_name)
                    if key2 in common_tables:
                        columns_from[(schema_name, table_name, column_name)] = (
                            data_type,
                            nullable,
                            ordinal_position,
                        )

                col_rows_to = session.execute(
                    select(
                        SchemaSnapshot.schema_name,
                        TableSnapshot.table_name,
                        ColumnSnapshot.column_name,
                        ColumnSnapshot.data_type,
                        ColumnSnapshot.nullable,
                        ColumnSnapshot.ordinal_position,
                    )
                    .join(
                        TableSnapshot,
                        TableSnapshot.schema_id == SchemaSnapshot.schema_id,
                    )
                    .join(
                        ColumnSnapshot,
                        ColumnSnapshot.table_id == TableSnapshot.table_id,
                    )
                    .where(SchemaSnapshot.snapshot_id == snapshot_to)
                ).all()

                for (
                    schema_name,
                    table_name,
                    column_name,
                    data_type,
                    nullable,
                    ordinal_position,
                ) in col_rows_to:
                    key2 = (schema_name, table_name)
                    if key2 in common_tables:
                        columns_to[(schema_name, table_name, column_name)] = (
                            data_type,
                            nullable,
                            ordinal_position,
                        )

        # ──── Step 2: Apply pure diff rules ────
        # Delegate rule application to diff_rules. The rules module is pure
        # (no DB, no side effects) — this separation keeps the engine testable
        # and the classification logic reusable.
        changes: List[Change] = []

        # --- Schema-level changes (v5.2) ---
        changes.extend(diff_schemas(schemas_from, schemas_to))

        # --- Table-level changes (v5.3) ---
        changes.extend(diff_tables(tables_from, tables_to))

        # --- Column-level changes (v5.4) ---
        changes.extend(
            diff_columns(
                common_tables=common_tables,
                columns_from=columns_from,
                columns_to=columns_to,
            )
        )

        # ──── Step 3: Classify severity and breaking flag ────
        # Severity and is_breaking are derived from change_type via static
        # maps in diff_rules — we re-hydrate each Change so downstream
        # consumers (persistence, impact analysis) see fully-populated rows.
        changes = [
            Change(
                object_type=c.object_type,
                object_identifier=c.object_identifier,
                change_type=c.change_type,
                before_state=c.before_state,
                after_state=c.after_state,
                severity=get_severity(c.change_type),
                is_breaking=is_breaking(c.change_type),
            )
            for c in changes
        ]

        # Deterministic ordering is critical: it guarantees reproducible test
        # fixtures AND the idempotent persistence below stores rows in a
        # predictable order that can be re-hydrated identically on re-runs.
        changes.sort(
            key=lambda c: (c.object_type, c.object_identifier, c.change_type)
        )

        # --- v5.5: persistence layer (append-only, idempotent) ---
        # Single session, single transaction, single commit. Any exception
        # results in a full rollback (no partial rows) and is propagated.
        #
        # Pre-construct a dummy ChangeEvent (not added to any session) when
        # there are changes, so that any constructor failures occur before we
        # attempt to write to the database.

        # Fail-fast construction check: if the ChangeEvent model rejects any
        # of our payloads (e.g. type/constraint issues), we want the error to
        # surface BEFORE we open a transaction — this keeps the DB untouched
        # on malformed input. The constructed object is intentionally discarded.
        if changes:
            _ = ChangeEvent(  # pragma: no cover - object is never persisted
                snapshot_from=snapshot_from,
                snapshot_to=snapshot_to,
                object_type=changes[0].object_type,
                object_identifier=changes[0].object_identifier,
                change_type=changes[0].change_type,
                before_state=changes[0].before_state,
                after_state=changes[0].after_state,
            )

        # ──── Step 4: Persist change events (idempotent, transactional) ────
        # The write path is intentionally separate from the read path above:
        # if anything in the compute phase throws, no rows are written.
        with Session(engine) as session:
            try:
                with session.begin():
                    # Idempotency probe: has this exact (from, to) pair already
                    # been computed and stored? If so, we re-project those rows
                    # instead of re-inserting duplicates.
                    existing_events = (
                        session.query(ChangeEvent)
                        .filter(
                            ChangeEvent.snapshot_from == snapshot_from,
                            ChangeEvent.snapshot_to == snapshot_to,
                        )
                        .order_by(
                            ChangeEvent.object_type,
                            ChangeEvent.object_identifier,
                            ChangeEvent.change_type,
                            ChangeEvent.change_id,
                        )
                        .all()
                    )

                    if existing_events:
                        # Idempotency: a concurrent worker inserted the diff between
                        # our outer check and the start of this transaction. Return
                        # the rows they inserted, respecting direction normalisation.
                        return _maybe_reverse(
                            [
                                Change(
                                    object_type=e.object_type,
                                    object_identifier=e.object_identifier,
                                    change_type=e.change_type,
                                    before_state=e.before_state,
                                    after_state=e.after_state,
                                    severity=e.severity or get_severity(e.change_type),
                                    is_breaking=e.is_breaking if e.is_breaking is not None else is_breaking(e.change_type),
                                )
                                for e in existing_events
                            ],
                            is_reversed,
                        )

                    if not changes:
                        # Nothing to persist, but keep behaviour consistent.
                        return []

                    # Persist all changes inside the same transaction so a
                    # mid-loop failure leaves zero rows behind (no partial diff).
                    for change in changes:
                        session.add(
                            ChangeEvent(
                                snapshot_from=snapshot_from,
                                snapshot_to=snapshot_to,
                                object_type=change.object_type,
                                object_identifier=change.object_identifier,
                                change_type=change.change_type,
                                before_state=change.before_state,
                                after_state=change.after_state,
                                severity=change.severity,
                                is_breaking=change.is_breaking,
                            )
                        )
            except Exception:
                session.rollback()
                raise

        return _maybe_reverse(changes, is_reversed)
