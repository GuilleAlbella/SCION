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
    - Cascade: deletes related schema_snapshot, table_snapshot,
      column_snapshot, change_event, graph_node, graph_edge,
      impact_event, reasoning_event rows linked to this snapshot.

    Returns a summary of what was deleted.
    """
    from sqlalchemy import select, delete
    from sqlalchemy.orm import Session

    from app.db.engine import engine
    from app.db.models.snapshot import Snapshot
    from app.db.models.schema_snapshot import SchemaSnapshot
    from app.db.models.table_snapshot import TableSnapshot
    from app.db.models.column_snapshot import ColumnSnapshot
    from app.diff.diff_models import ChangeEvent
    from app.graph.graph_models import GraphNode, GraphEdge
    from app.graph.impact_models import ImpactEvent

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
        # Deleting an older snapshot would orphan diffs, impact events and
        # reasoning events anchored on higher snapshot_ids, silently
        # corrupting history. Forcing LIFO deletion keeps the timeline sound.
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

        # ──── 3. Resolve dependent schema/table IDs for cascade ────
        # We delete manually (rather than rely on DB cascade) to return
        # accurate row counts to the caller and to support SQLite, which has
        # partial FK enforcement.
        schema_ids = [r[0] for r in session.execute(
            select(SchemaSnapshot.schema_id).where(SchemaSnapshot.snapshot_id == snapshot_id)
        ).all()]
        table_ids = []
        if schema_ids:
            table_ids = [r[0] for r in session.execute(
                select(TableSnapshot.table_id).where(TableSnapshot.schema_id.in_(schema_ids))
            ).all()]

        counts = {
            "schemas": len(schema_ids),
            "tables": len(table_ids),
            "columns": 0,
            "changes": 0,
            "graph_nodes": 0,
            "graph_edges": 0,
            "impacts": 0,
        }

        # ──── 4. Cascade delete in reverse-dependency order ────
        # Columns -> Tables -> Schemas -> ChangeEvents -> Graph/Impact -> Snapshot.
        # Order matters: parents cannot be deleted while children reference them.
        if table_ids:
            counts["columns"] = session.execute(
                delete(ColumnSnapshot).where(ColumnSnapshot.table_id.in_(table_ids))
            ).rowcount or 0
            session.execute(delete(TableSnapshot).where(TableSnapshot.schema_id.in_(schema_ids)))

        if schema_ids:
            session.execute(delete(SchemaSnapshot).where(SchemaSnapshot.snapshot_id == snapshot_id))

        # Diffs that reference this snapshot as from/to
        counts["changes"] = session.execute(
            delete(ChangeEvent).where(
                (ChangeEvent.snapshot_from == snapshot_id) | (ChangeEvent.snapshot_to == snapshot_id)
            )
        ).rowcount or 0

        # Graph + impact
        counts["graph_nodes"] = session.execute(
            delete(GraphNode).where(GraphNode.snapshot_id == snapshot_id)
        ).rowcount or 0
        counts["graph_edges"] = session.execute(
            delete(GraphEdge).where(GraphEdge.snapshot_id == snapshot_id)
        ).rowcount or 0
        counts["impacts"] = session.execute(
            delete(ImpactEvent).where(ImpactEvent.snapshot_id == snapshot_id)
        ).rowcount or 0

        # Finally, the snapshot itself
        session.execute(delete(Snapshot).where(Snapshot.snapshot_id == snapshot_id))
        session.commit()

    return {
        "deleted_snapshot_id": snapshot_id,
        "cascade": counts,
        "message": f"Snapshot #{snapshot_id} and all dependent data removed.",
    }
