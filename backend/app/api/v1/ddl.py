from __future__ import annotations

"""DDL Generation API (v1).

Generates SQL DDL statements for detected changes between snapshots.
Optionally runs TAISA review on the generated DDL for risk warnings.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent
from app.ddl.ddl_generator import generate_ddl_for_change


router = APIRouter(prefix="/ddl", tags=["ddl"])


class DDLItem(BaseModel):
    change_id: int
    object_identifier: str
    change_type: str
    severity: str | None = None
    is_breaking: bool | None = None
    ddl_statements: List[str]
    ddl_combined: str
    taisa_warnings: List[str] = []


class DDLResponse(BaseModel):
    snapshot_from: int
    snapshot_to: int
    total: int
    items: List[DDLItem]


@router.get(
    "/{snapshot_from}/{snapshot_to}",
    status_code=status.HTTP_200_OK,
    response_model=DDLResponse,
)
def get_ddl(snapshot_from: int, snapshot_to: int) -> Dict[str, Any]:
    """Generate DDL for all changes between two snapshots.

    Optionally enriches with TAISA risk warnings if TAISA is available.
    """
    from app.db.models.snapshot import Snapshot

    # Same cumulative-pairs walk as the diff endpoint — DDL must cover every
    # intermediate step, not just the endpoints, otherwise migrations would
    # skip changes applied in between.
    with Session(bind=engine) as session:
        all_snaps = session.execute(
            select(Snapshot.snapshot_id)
            .where(
                Snapshot.snapshot_id >= snapshot_from,
                Snapshot.snapshot_id <= snapshot_to,
            )
            .order_by(Snapshot.snapshot_id)
        ).scalars().all()

    pairs = []
    if len(all_snaps) >= 2:
        for i in range(len(all_snaps) - 1):
            pairs.append((all_snaps[i], all_snaps[i + 1]))
    else:
        pairs = [(snapshot_from, snapshot_to)]

    # Load change events
    with Session(bind=engine) as session:
        rows = []
        for sf, st in pairs:
            pair_rows = (
                session.query(ChangeEvent)
                .filter(
                    ChangeEvent.snapshot_from == sf,
                    ChangeEvent.snapshot_to == st,
                )
                .all()
            )
            rows.extend(pair_rows)

    if not rows:
        return {
            "snapshot_from": snapshot_from,
            "snapshot_to": snapshot_to,
            "total": 0,
            "items": [],
        }

    # Generate DDL for each change
    items = []
    for row in rows:
        stmts = generate_ddl_for_change(
            change_type=row.change_type,
            object_type=row.object_type,
            object_identifier=row.object_identifier,
            before_state=row.before_state,
            after_state=row.after_state,
        )

        # Only invoke TAISA for breaking changes — non-breaking DDL rarely
        # warrants AI review and each call has real LLM cost/latency.
        warnings: List[str] = []
        if row.is_breaking:
            try:
                from app.engine_registry import get_engine_states, get_taisa_client
                states = get_engine_states()
                if states.get("taisa_ready"):
                    taisa = get_taisa_client()
                    ddl_text = "\n".join(stmts)
                    answer = taisa.answer_question(
                        change_id=row.change_id,
                        question=f"Review this DDL for risks and warnings:\n{ddl_text}",
                        context={"object": row.object_identifier, "change_type": row.change_type},
                    )
                    if answer:
                        warnings = [line.strip() for line in answer.split("\n") if line.strip()]
            except Exception:
                pass

        items.append({
            "change_id": row.change_id,
            "object_identifier": row.object_identifier,
            "change_type": row.change_type,
            "severity": row.severity,
            "is_breaking": row.is_breaking,
            "ddl_statements": stmts,
            "ddl_combined": "\n".join(stmts),
            "taisa_warnings": warnings,
        })

    return {
        "snapshot_from": snapshot_from,
        "snapshot_to": snapshot_to,
        "total": len(items),
        "items": items,
    }
