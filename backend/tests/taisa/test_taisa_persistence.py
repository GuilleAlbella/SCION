from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.diff.diff_models import ChangeEvent
from app.graph.graph_models import GraphNode
from app.graph.impact_models import ImpactEvent
from app.taisa.taisa_models import ReasoningEvent


def _reset_state() -> None:
    with Session(engine) as session:
        session.query(ReasoningEvent).delete()
        session.query(ImpactEvent).delete()
        session.query(GraphNode).delete()
        session.query(ChangeEvent).delete()
        session.query(Snapshot).delete()
        session.commit()


def test_reasoning_event_table_exists() -> None:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "reasoning_event" in tables


def test_can_insert_reasoning_event() -> None:
    _reset_state()

    with Session(engine) as session:
        event = ReasoningEvent(
            change_id=123,
            taisa_version="7.3-mvp",
            classification="NON_BREAKING",
            risk_level="LOW",
            recommendations=["Validate downstream reports"],
            explanation="Mock reasoning result for testing.",
        )
        session.add(event)
        session.commit()

        fetched = session.query(ReasoningEvent).one()

    assert fetched.reasoning_id is not None
    assert fetched.change_id == 123
    assert fetched.taisa_version == "7.3-mvp"
    assert fetched.classification == "NON_BREAKING"
    assert fetched.risk_level == "LOW"
    assert fetched.recommendations == ["Validate downstream reports"]
    assert isinstance(fetched.explanation, str) and fetched.explanation
    assert fetched.created_at is not None


def test_reasoning_event_insertion_is_isolated_from_other_tables() -> None:
    _reset_state()

    with Session(engine) as session:
        snap_before = session.query(Snapshot).count()
        change_before = session.query(ChangeEvent).count()
        node_before = session.query(GraphNode).count()
        impact_before = session.query(ImpactEvent).count()

    with Session(engine) as session:
        event = ReasoningEvent(
            change_id=None,
            taisa_version="7.3-mvp",
            classification="INFORMATIONAL",
            risk_level="LOW",
            recommendations=["No action required"],
            explanation="Informational reasoning event.",
        )
        session.add(event)
        session.commit()

    with Session(engine) as session:
        snap_after = session.query(Snapshot).count()
        change_after = session.query(ChangeEvent).count()
        node_after = session.query(GraphNode).count()
        impact_after = session.query(ImpactEvent).count()
        reasoning_count = session.query(ReasoningEvent).count()

    assert snap_before == snap_after
    assert change_before == change_after
    assert node_before == node_after
    assert impact_before == impact_after
    assert reasoning_count == 1
