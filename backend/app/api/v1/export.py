from __future__ import annotations

"""Export API (v1).

Generates CSV exports for changes, impact, usage, and intelligence data.
"""

import csv
import io
from typing import Any, Dict, List

from fastapi import APIRouter, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent


router = APIRouter(prefix="/export", tags=["export"])


def _make_csv_response(rows: List[List[str]], headers: List[str], filename: str) -> StreamingResponse:
    """Build a streaming CSV response."""
    # StringIO + StreamingResponse is lighter than buffering the whole CSV in
    # memory as bytes; for larger exports we'd switch to a generator.
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/changes/{snapshot_from}/{snapshot_to}")
def export_changes(snapshot_from: int, snapshot_to: int):
    """Export changes as CSV."""
    from app.db.models.snapshot import Snapshot

    with Session(bind=engine) as session:
        all_snaps = session.execute(
            select(Snapshot.snapshot_id)
            .where(Snapshot.snapshot_id >= snapshot_from, Snapshot.snapshot_id <= snapshot_to)
            .order_by(Snapshot.snapshot_id)
        ).scalars().all()

    pairs = []
    if len(all_snaps) >= 2:
        for i in range(len(all_snaps) - 1):
            pairs.append((all_snaps[i], all_snaps[i + 1]))
    else:
        pairs = [(snapshot_from, snapshot_to)]

    with Session(bind=engine) as session:
        rows_db = []
        for sf, st in pairs:
            rows_db.extend(
                session.query(ChangeEvent)
                .filter(ChangeEvent.snapshot_from == sf, ChangeEvent.snapshot_to == st)
                .all()
            )

    headers = ["Change ID", "Object Type", "Object Identifier", "Change Type", "Severity", "Breaking", "Snapshot From", "Snapshot To", "Detected At"]
    rows = []
    for r in rows_db:
        rows.append([
            str(r.change_id), r.object_type, r.object_identifier, r.change_type,
            r.severity or "LOW", "YES" if r.is_breaking else "NO",
            str(r.snapshot_from), str(r.snapshot_to),
            r.detected_at.isoformat() if r.detected_at else "",
        ])

    return _make_csv_response(rows, headers, f"scion_changes_{snapshot_from}_to_{snapshot_to}.csv")


@router.get("/impact/{snapshot_from}/{snapshot_to}")
def export_impact(snapshot_from: int, snapshot_to: int):
    """Export impact analysis as CSV."""
    from app.graph.blast_radius import compute_batch_impact
    from app.engine_registry import get_engine_states

    # Graceful degradation: if the graph engine is stopped, we still return
    # SOMETHING (a plain changes CSV) rather than failing the download.
    if not get_engine_states().get("graph_ready"):
        return export_changes(snapshot_from, snapshot_to)

    result = compute_batch_impact(snapshot_from, snapshot_to)
    headers = ["Change ID", "Object", "Change Type", "Severity", "Breaking", "Direct Count", "Indirect Count", "Impact Score"]
    rows = []
    for c in result.changes:
        rows.append([
            str(c.change_id), c.object_identifier, c.change_type, c.severity,
            "YES" if c.is_breaking else "NO",
            str(c.direct_count), str(c.indirect_count), f"{c.impact_score:.2f}",
        ])

    return _make_csv_response(rows, headers, f"scion_impact_{snapshot_from}_to_{snapshot_to}.csv")


@router.get("/usage")
def export_usage():
    """Export usage summary as CSV."""
    from app.usage.usage_models import UsageEvent

    with Session(bind=engine) as session:
        rows_db = session.execute(
            select(UsageEvent).order_by(desc(UsageEvent.query_count))
        ).scalars().all()

    headers = ["Object Name", "Object Type", "Schema Name", "Query Count", "User Count"]
    rows = []
    for r in rows_db:
        rows.append([
            r.object_name, r.object_type or "", r.schema_name or "",
            str(r.query_count), str(r.user_count),
        ])

    return _make_csv_response(rows, headers, "scion_usage_summary.csv")


@router.get("/intelligence/{snapshot_id}")
def export_intelligence(snapshot_id: int):
    """Export criticality scores as CSV."""
    from app.usage.usage_models import ObjectCriticality

    with Session(bind=engine) as session:
        rows_db = session.execute(
            select(ObjectCriticality)
            .where(ObjectCriticality.snapshot_id == snapshot_id)
            .order_by(desc(ObjectCriticality.combined_score))
        ).scalars().all()

    headers = ["Object Name", "Usage Score", "Graph Score", "Combined Score", "Criticality Level"]
    rows = []
    for r in rows_db:
        rows.append([
            r.object_name, f"{r.usage_score:.2f}", f"{r.graph_score:.2f}",
            f"{r.combined_score:.2f}", r.criticality_level,
        ])

    return _make_csv_response(rows, headers, f"scion_intelligence_{snapshot_id}.csv")
