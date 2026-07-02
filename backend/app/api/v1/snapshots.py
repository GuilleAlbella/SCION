from __future__ import annotations

"""Snapshots API (v1).

This module defines the API surface for snapshot-related operations in
version 1 of the backend API.

Responsibilities (future v8.3+):
- Orchestrate calls to the Snapshot Engine.
- Expose endpoints to list and trigger snapshots.
- Provide traceability by `snapshot_id`.

Non-responsibilities:
- Implementing snapshot logic itself.
- Direct database manipulation outside of the engine.
- UI concerns.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.engine_registry import get_snapshot_orchestrator


router = APIRouter(prefix="/snapshots", tags=["snapshots"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create snapshot")
def create_snapshot() -> dict[str, str]:
    """Trigger a new snapshot execution via the Snapshot Orchestrator.

    Behaviour (MVP v8.3.2):

    - Stateless: no in-memory state is kept between calls.
    - Thin layer: delegates the actual work to the existing snapshot
      orchestrator; no snapshot logic is reimplemented here.
    - No payload is accepted for now; snapshot metadata is minimal and
      hard-coded.
    - Exceptions from the engine/orchestrator are *not* swallowed; they
      propagate as 5xx responses so that failures are visible to callers.
    """

    # Use the shared, eagerly initialised snapshot orchestrator from the
    # engine registry. This avoids per-request construction and ensures that
    # failures are detected at application startup time.

    try:
        orchestrator = get_snapshot_orchestrator()
    except RuntimeError as exc:
        # Surface a clear 503 when the snapshot engine has been stopped via the
        # control plane.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    snapshot_id = orchestrator.create_snapshot(
        source_system="api",
        description="Snapshot created via API v1",
        is_baseline=False,
    )

    # The engine returns an integer primary key; the API exposes it as a
    # string without enforcing any additional format.
    return {"snapshot_id": str(snapshot_id)}


@router.get("", summary="List snapshots")
def list_snapshots() -> dict[str, list[dict[str, str]]]:
    """Return a read-only list of available snapshots.

    Behaviour (MVP v8.3.2):

    - Read-only: performs a SELECT over the snapshot table, ordered by
      creation time when possible.
    - No side effects: does not mutate the database or start long-running
      processes.
    - Does not assume any existing snapshots; returns an empty list when
      none are present.
    """

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.engine import engine
    from app.db.models.snapshot import Snapshot

    with Session(bind=engine) as session:
        stmt = select(Snapshot).order_by(Snapshot.snapshot_time.desc())
        rows = session.execute(stmt).scalars().all()

    snapshots = [
        {
            "snapshot_id": str(row.snapshot_id),
            "created_at": row.snapshot_time.isoformat(),
            "source_system": row.source_system,
            "description": row.description or "",
        }
        for row in rows
    ]

    return {"snapshots": snapshots}


@router.delete(
    "/{snapshot_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a snapshot (only the latest, with cascade)",
)
def delete_snapshot(snapshot_id: int, confirm_id: int) -> dict[str, Any]:
    """Delete a snapshot and its dependent data.

    Safety rules (SCION v1.03+):
    - Only the *latest* snapshot (highest snapshot_id) can be deleted.
      This prevents accidental deletion of baselines or intermediate
      snapshots on which diffs/impact/reasoning depend.
    - The caller must repeat the `snapshot_id` as `confirm_id` query
      parameter. If they don't match, the request is rejected.
    - Cascade: deletes every dependent row linked to this snapshot,
      directly or transitively. The cascade covers the dict ingest
      sub-tables (column / index / partitioning / ddl_text) added in
      v1.14.02 and the parser tables (process / step /
      attribute_lineage) added in v1.13.

    Scale: the previous implementation materialised every table_id of
    a snapshot into a Python list and fed it to
    `IN (?, ?, ?, ...)` for the cascade DELETEs. On the full
    Transcend-DevTest extract (~239k tables) that produced a SQL
    statement with 239k+ host parameters, which SQLite rejects with
    "too many SQL variables". We now use scalar subqueries so the
    parameter count stays at 1 per DELETE regardless of how many rows
    match.

    Returns a summary of what was deleted.

    Disk space: SQLite's default `auto_vacuum = NONE` means a DELETE
    only marks pages as free, never shrinks the file. For an
    industrial-scale snapshot (Transcend-DevTest deletes ~11.5M rows)
    the file would stay at its high-water mark of several GB until
    a manual VACUUM. Most users don't know that SQLite-internal
    detail, so the cascade now ends with a VACUUM that physically
    reclaims the freed space. Reported back in the response so the
    UI can show "freed 2.4 GB" rather than leave the user wondering
    why their disk didn't change.
    """
    import logging
    import os
    import time

    from sqlalchemy import delete, func, select, text
    from sqlalchemy.orm import Session

    from app.db.engine import engine

    _delete_logger = logging.getLogger(__name__)
    from app.db.models.column_snapshot import ColumnSnapshot
    from app.db.models.ddl_text_snapshot import DDLTextSnapshot
    from app.db.models.index_snapshot import IndexSnapshot
    from app.db.models.partitioning_snapshot import PartitioningSnapshot
    from app.db.models.schema_snapshot import SchemaSnapshot
    from app.db.models.snapshot import Snapshot
    from app.db.models.table_snapshot import TableSnapshot
    from app.diff.diff_models import ChangeEvent
    from app.graph.graph_models import GraphEdge, GraphNode
    from app.graph.impact_models import ChangeImpactSummary, ImpactEvent
    from app.usage.usage_models import ObjectCriticality, UsageEvent

    # Optional dependents — present in some checkouts only. We import
    # defensively so an older branch that hasn't migrated the parser
    # tables still serves the delete endpoint.
    try:
        from app.db.models.attribute_lineage import AttributeLineage
    except ImportError:
        AttributeLineage = None  # type: ignore[assignment]
    try:
        from app.db.models.process import Process
    except ImportError:
        Process = None  # type: ignore[assignment]
    try:
        from app.db.models.step import Step
    except ImportError:
        Step = None  # type: ignore[assignment]

    if confirm_id != snapshot_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="confirm_id must match snapshot_id (repeat the ID to confirm deletion).",
        )

    with Session(bind=engine) as session:
        # ──── 1. Verify the snapshot exists at all ────
        target = session.execute(
            select(Snapshot).where(Snapshot.snapshot_id == snapshot_id)
        ).scalar_one_or_none()

        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Snapshot #{snapshot_id} does not exist.",
            )

        # ──── 2. Enforce "only the latest can be deleted" invariant ────
        # Deleting an older snapshot would orphan diffs, impact events
        # and reasoning events anchored on higher snapshot_ids, silently
        # corrupting history. Forcing LIFO deletion keeps the timeline
        # sound.
        latest = session.execute(
            select(Snapshot).order_by(Snapshot.snapshot_id.desc()).limit(1)
        ).scalar_one()

        if latest.snapshot_id != snapshot_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Only the latest snapshot (#{latest.snapshot_id}) can be deleted. "
                    f"Deleting an older snapshot would corrupt diffs, impact and reasoning events. "
                    f"To remove multiple snapshots, delete them one at a time starting from the latest."
                ),
            )

        # ──── 3. Build cascade subqueries (server-side, never materialised) ────
        # `schema_id_subq` and `table_id_subq` are SQLAlchemy `select()`
        # expressions, not Python lists. SQLite re-evaluates them at the
        # moment each DELETE runs, so as long as we delete children
        # before parents the cascade stays correct without ever shipping
        # IDs through the wire.
        schema_id_subq = select(SchemaSnapshot.schema_id).where(
            SchemaSnapshot.snapshot_id == snapshot_id
        )
        table_id_subq = select(TableSnapshot.table_id).where(
            TableSnapshot.schema_id.in_(schema_id_subq)
        )

        # ──── 4. Aggregate counts up front (single SQL each) ────
        # We compute counts before the deletes so the response can
        # report them without a second pass. `func.count()` runs
        # entirely server-side; no row materialisation in Python.
        counts: dict[str, int] = {
            "schemas": session.scalar(
                select(func.count())
                .select_from(SchemaSnapshot)
                .where(SchemaSnapshot.snapshot_id == snapshot_id)
            ) or 0,
            "tables": session.scalar(
                select(func.count())
                .select_from(TableSnapshot)
                .where(TableSnapshot.schema_id.in_(schema_id_subq))
            ) or 0,
            "columns": session.scalar(
                select(func.count())
                .select_from(ColumnSnapshot)
                .where(ColumnSnapshot.table_id.in_(table_id_subq))
            ) or 0,
            "indices": session.scalar(
                select(func.count())
                .select_from(IndexSnapshot)
                .where(IndexSnapshot.table_id.in_(table_id_subq))
            ) or 0,
            "partitioning": session.scalar(
                select(func.count())
                .select_from(PartitioningSnapshot)
                .where(PartitioningSnapshot.table_id.in_(table_id_subq))
            ) or 0,
            "ddl_text": session.scalar(
                select(func.count())
                .select_from(DDLTextSnapshot)
                .where(DDLTextSnapshot.table_id.in_(table_id_subq))
            ) or 0,
            "changes": 0,
            "impact_summaries": 0,
            "graph_nodes": 0,
            "graph_edges": 0,
            "impacts": 0,
            "criticality": 0,
            "usage_events": 0,
        }

        # ──── 5. Cascade DELETE in reverse-dependency order ────
        # Children of TableSnapshot first (every table-keyed sub-table),
        # then TableSnapshot, then SchemaSnapshot, then everything
        # keyed directly off snapshot_id. Each statement uses the
        # subqueries above so we never blow past SQLite's host-param
        # limit.
        session.execute(
            delete(IndexSnapshot).where(IndexSnapshot.table_id.in_(table_id_subq))
        )
        session.execute(
            delete(PartitioningSnapshot).where(
                PartitioningSnapshot.table_id.in_(table_id_subq)
            )
        )
        session.execute(
            delete(DDLTextSnapshot).where(DDLTextSnapshot.table_id.in_(table_id_subq))
        )
        session.execute(
            delete(ColumnSnapshot).where(ColumnSnapshot.table_id.in_(table_id_subq))
        )
        session.execute(
            delete(TableSnapshot).where(TableSnapshot.schema_id.in_(schema_id_subq))
        )
        session.execute(
            delete(SchemaSnapshot).where(SchemaSnapshot.snapshot_id == snapshot_id)
        )

        # ChangeImpactSummary has a change_id FK to ChangeEvent but no
        # DB-level ON DELETE CASCADE (see the model docstring) — it was
        # never actually wired into this cascade, so deleting a snapshot
        # left its impact summaries orphaned (still readable by change_id,
        # pointing at nothing). Must run BEFORE the ChangeEvent delete
        # below since it needs those rows to resolve which change_ids
        # belong to this snapshot.
        affected_change_id_subq = select(ChangeEvent.change_id).where(
            (ChangeEvent.snapshot_from == snapshot_id)
            | (ChangeEvent.snapshot_to == snapshot_id)
        )
        counts["impact_summaries"] = session.execute(
            delete(ChangeImpactSummary).where(
                ChangeImpactSummary.change_id.in_(affected_change_id_subq)
            )
        ).rowcount or 0

        # Diffs that reference this snapshot as from/to.
        counts["changes"] = session.execute(
            delete(ChangeEvent).where(
                (ChangeEvent.snapshot_from == snapshot_id)
                | (ChangeEvent.snapshot_to == snapshot_id)
            )
        ).rowcount or 0

        # Graph + impact.
        counts["graph_nodes"] = session.execute(
            delete(GraphNode).where(GraphNode.snapshot_id == snapshot_id)
        ).rowcount or 0
        counts["graph_edges"] = session.execute(
            delete(GraphEdge).where(GraphEdge.snapshot_id == snapshot_id)
        ).rowcount or 0
        counts["impacts"] = session.execute(
            delete(ImpactEvent).where(ImpactEvent.snapshot_id == snapshot_id)
        ).rowcount or 0

        # Criticality scores keyed by snapshot_id (no FK declared, so
        # the DB wouldn't cascade them — we have to do it explicitly).
        counts["criticality"] = session.execute(
            delete(ObjectCriticality).where(
                ObjectCriticality.snapshot_id == snapshot_id
            )
        ).rowcount or 0

        # Usage events keyed by snapshot_id (added v1.21.54 — previously
        # this table had no snapshot linkage at all, so deleting a
        # snapshot silently left its usage rows behind, and a later
        # re-import of the same PDCR file would double-count them). Rows
        # persisted before v1.21.54 have snapshot_id=NULL and are left
        # alone here; there's no way to attribute them retroactively.
        counts["usage_events"] = session.execute(
            delete(UsageEvent).where(UsageEvent.snapshot_id == snapshot_id)
        ).rowcount or 0

        # Parser-pipeline tables (v1.13+). Process is parent of Step,
        # so Step deletes first. AttributeLineage is independent.
        if Step is not None:
            session.execute(
                delete(Step).where(Step.snapshot_id == snapshot_id)
            )
        if Process is not None:
            session.execute(
                delete(Process).where(Process.snapshot_id == snapshot_id)
            )
        if AttributeLineage is not None:
            session.execute(
                delete(AttributeLineage).where(
                    AttributeLineage.snapshot_id == snapshot_id
                )
            )

        # Finally, the snapshot itself.
        session.execute(delete(Snapshot).where(Snapshot.snapshot_id == snapshot_id))
        session.commit()

    # ──── 6. VACUUM to physically reclaim freed pages ────
    # SQLite default `auto_vacuum = NONE` keeps deleted pages as free
    # space inside the file — disk usage doesn't change after a DELETE.
    # Running VACUUM rebuilds the file without the free pages, returning
    # the bytes to the filesystem. For a 240k-table cascade this typically
    # frees several GB.
    #
    # VACUUM cannot run inside a transaction, so we open a fresh
    # connection in AUTOCOMMIT mode (SQLAlchemy 2.0 autobegins on every
    # `connect()`, which would otherwise wrap the VACUUM in a BEGIN and
    # SQLite would reject it with "cannot VACUUM from within a
    # transaction"). The VACUUM holds an exclusive lock on the DB while
    # it runs — for our 800 MB-class file that's typically 5-15 s,
    # during which other API calls would 503. Acceptable for a
    # demo/dev workload; production would either skip it or queue
    # deletes for off-hours.
    vacuum_info: dict = {
        "bytes_before": None,
        "bytes_after": None,
        "bytes_freed": None,
        "elapsed_seconds": None,
        "skipped_reason": None,
    }

    db_path = engine.url.database
    if not db_path or db_path == ":memory:":
        # Engine isn't backed by a real file (e.g. in-memory test DB).
        # Nothing to reclaim; report and move on.
        vacuum_info["skipped_reason"] = "non-file engine"
    else:
        try:
            vacuum_info["bytes_before"] = os.path.getsize(db_path)
        except OSError as e:
            _delete_logger.warning(
                "[delete] could not stat DB before VACUUM: %s", e,
            )

        t0 = time.perf_counter()
        try:
            with engine.connect().execution_options(
                isolation_level="AUTOCOMMIT",
            ) as conn:
                conn.execute(text("VACUUM"))
            vacuum_info["elapsed_seconds"] = time.perf_counter() - t0
            try:
                vacuum_info["bytes_after"] = os.path.getsize(db_path)
                if (
                    vacuum_info["bytes_before"] is not None
                    and vacuum_info["bytes_after"] is not None
                ):
                    vacuum_info["bytes_freed"] = (
                        vacuum_info["bytes_before"] - vacuum_info["bytes_after"]
                    )
            except OSError as e:
                _delete_logger.warning(
                    "[delete] could not stat DB after VACUUM: %s", e,
                )
            _delete_logger.info(
                "[delete] VACUUM done in %.2fs — before=%s after=%s freed=%s",
                vacuum_info["elapsed_seconds"],
                vacuum_info["bytes_before"],
                vacuum_info["bytes_after"],
                vacuum_info["bytes_freed"],
            )
        except Exception as e:
            # A failed VACUUM is non-fatal: the snapshot was already
            # deleted, the user's data is still consistent, the file
            # just stays at its old size. Report the reason so the UI
            # can mention it but don't 500 the response.
            vacuum_info["skipped_reason"] = f"{type(e).__name__}: {e}"
            _delete_logger.warning(
                "[delete] VACUUM failed (snapshot delete already succeeded): %s", e,
            )

    return {
        "deleted_snapshot_id": snapshot_id,
        "cascade": counts,
        "vacuum": vacuum_info,
        "message": f"Snapshot #{snapshot_id} and all dependent data removed.",
    }
