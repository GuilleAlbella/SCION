from __future__ import annotations

"""Reasoning API (v1) — TAISA individual and batch analysis."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.engine_registry import get_taisa_client


router = APIRouter(prefix="/reasoning", tags=["reasoning"])


class ReasoningResponse(BaseModel):
    change_id: int
    classification: str
    risk_level: str
    recommendations: List[str] = []
    explanation: str = ""


class BatchReasoningRequest(BaseModel):
    snapshot_from: int
    snapshot_to: int


class BatchReasoningResponse(BaseModel):
    snapshot_from: int
    snapshot_to: int
    classification: str
    risk_level: str
    recommendations: List[str]
    explanation: str
    changes_analyzed: int


class ChatMessage(BaseModel):
    role: str          # "user" or "taisa"
    text: str

class ReasoningQuestionRequest(BaseModel):
    question: str
    context: Optional[Dict[str, Any]] = None
    history: Optional[List[ChatMessage]] = None


# NOTE: FastAPI matches routes top-down. /batch must be declared BEFORE the
# generic /{change_id} route, otherwise "batch" would be interpreted as a
# change_id and fail with a 422.
@router.post(
    "/batch",
    status_code=status.HTTP_201_CREATED,
    response_model=BatchReasoningResponse,
)
def execute_batch_reasoning(request: BatchReasoningRequest) -> Dict[str, Any]:
    """Run TAISA reasoning on ALL changes in a diff pair at once."""

    from sqlalchemy.orm import Session
    from app.db.engine import engine
    from app.db.models.snapshot import Snapshot
    from app.diff.diff_models import ChangeEvent
    from app.graph.blast_radius import compute_batch_impact
    from app.taisa.taisa_models import ReasoningEvent
    from app.taisa.taisa_prompts import PROMPT_CONTRACT_VERSION

    try:
        client = get_taisa_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=str(exc)) from exc

    # Reuse the same cumulative-pairs logic used by /diff to keep batch
    # reasoning consistent with what the user sees in the diff viewer.
    from app.graph.blast_radius import _load_all_changes
    events = _load_all_changes(request.snapshot_from, request.snapshot_to)

    with Session(bind=engine) as session:
        snapshot = session.query(Snapshot).filter(
            Snapshot.snapshot_id == request.snapshot_to
        ).first()

    if not events:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No changes found for this snapshot pair.")

    # Compute batch impact for blast radius
    batch_impact = compute_batch_impact(request.snapshot_from, request.snapshot_to)

    changes_data = [
        {
            "change_type": e.change_type,
            "object_identifier": e.object_identifier,
            "object_type": e.object_type,
            "severity": e.severity or "LOW",
            "is_breaking": e.is_breaking or False,
        }
        for e in events
    ]

    from dataclasses import asdict
    blast_data = asdict(batch_impact.blast_radius)

    context_data = {
        "source_system": snapshot.source_system if snapshot else "unknown",
        "snapshot_from": request.snapshot_from,
        "snapshot_to": request.snapshot_to,
    }

    result = client.analyze_batch(
        changes=changes_data,
        blast_radius=blast_data,
        context=context_data,
    )

    # Persist a single ReasoningEvent with change_id=NULL to mark this as a
    # batch-level verdict (distinguishable from per-change reasoning rows).
    with Session(bind=engine) as session:
        session.add(ReasoningEvent(
            change_id=None,
            taisa_version=PROMPT_CONTRACT_VERSION,
            classification=result.classification,
            risk_level=result.risk_level,
            recommendations=result.recommendations,
            explanation=result.explanation,
        ))
        session.commit()

    return {
        "snapshot_from": request.snapshot_from,
        "snapshot_to": request.snapshot_to,
        "classification": result.classification,
        "risk_level": result.risk_level,
        "recommendations": result.recommendations,
        "explanation": result.explanation,
        "changes_analyzed": len(events),
    }


@router.post(
    "/{change_id}",
    status_code=status.HTTP_201_CREATED,
    response_model=ReasoningResponse,
)
def execute_reasoning(change_id: int) -> ReasoningResponse:
    """Run TAISA reasoning for a single change."""

    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from app.db.engine import engine
    from app.db.models.snapshot import Snapshot
    from app.diff.diff_models import ChangeEvent
    from app.graph.graph_models import GraphNode
    from app.graph.impact_models import ImpactEvent
    from app.taisa.taisa_models import ReasoningEvent
    from app.taisa.taisa_prompts import PROMPT_CONTRACT_VERSION

    with Session(bind=engine) as session:
        change = session.execute(
            select(ChangeEvent).where(ChangeEvent.change_id == change_id)
        ).scalar_one_or_none()

        if change is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="change_id does not exist.")

        snapshot = session.execute(
            select(Snapshot).where(Snapshot.snapshot_id == change.snapshot_to)
        ).scalar_one_or_none()

        if snapshot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="snapshot not found.")

        # Join ImpactEvent -> GraphNode so we can feed TAISA object names
        # (not opaque node ids) — critical for the LLM to reason usefully.
        impact_rows = session.execute(
            select(ImpactEvent, GraphNode)
            .join(GraphNode, GraphNode.node_id == ImpactEvent.impacted_node_id)
            .where(
                ImpactEvent.change_id == change_id,
                ImpactEvent.snapshot_id == change.snapshot_to,
            )
        ).all()

    change_event_payload = {
        "object_type": change.object_type,
        "object_identifier": change.object_identifier,
        "change_type": change.change_type,
        "before_state": change.before_state,
        "after_state": change.after_state,
    }

    impacts_payload = [
        {
            "object": node.object_name,
            "object_type": node.object_type,
            "impact_level": impact.impact_level,
            "depth": impact.depth,
        }
        for impact, node in impact_rows
    ]

    context_payload = {
        "source_system": snapshot.source_system,
        "snapshot_time": snapshot.snapshot_time.isoformat(),
    }

    try:
        client = get_taisa_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=str(exc)) from exc

    result = client.analyze_change(
        change_event=change_event_payload,
        impacts=impacts_payload,
        context=context_payload,
    )

    with Session(bind=engine) as session:
        session.add(ReasoningEvent(
            change_id=change_id,
            taisa_version=result.raw_response.get("prompt_version", PROMPT_CONTRACT_VERSION),
            classification=result.classification,
            risk_level=result.risk_level,
            recommendations=result.recommendations,
            explanation=result.explanation,
        ))
        session.commit()

    return ReasoningResponse(
        change_id=change_id,
        classification=result.classification,
        risk_level=result.risk_level,
        recommendations=result.recommendations,
        explanation=result.explanation,
    )


@router.post("/{change_id}/ask", status_code=status.HTTP_200_OK)
def ask_reasoning_question(change_id: int, payload: ReasoningQuestionRequest) -> dict:
    """Answer a user question based on existing reasoning."""

    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Missing question")

    try:
        client = get_taisa_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=str(exc)) from exc

    history_dicts = None
    if payload.history:
        history_dicts = [{"role": m.role, "text": m.text} for m in payload.history]

    try:
        answer = client.answer_question(
            change_id=change_id,
            question=question,
            context=payload.context,
            history=history_dicts,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=str(exc)) from exc

    return {"answer": answer}
