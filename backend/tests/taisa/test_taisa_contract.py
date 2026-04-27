from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict, List

import json
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.diff.diff_models import ChangeEvent
from app.graph.graph_models import GraphNode
from app.graph.impact_models import ImpactEvent
from app.taisa import TaisaClient, TaisaClientConfig
from app.taisa.taisa_models import TaisaAnalysisRequest
from app.taisa.taisa_prompts import PROMPT_CONTRACT_VERSION


def _reset_state() -> None:
    """Best-effort cleanup for entities that TAISA must not touch.

    TAISA itself will never import or persist these models. We only use
    them here to ensure that calling TaisaClient has no side effects.
    """

    with Session(engine) as session:
        session.query(ImpactEvent).delete()
        session.query(GraphNode).delete()
        session.query(ChangeEvent).delete()
        session.query(Snapshot).delete()
        session.commit()


def _make_minimal_input() -> tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    change_event = {
        "object_type": "COLUMN",
        "object_identifier": "sales.orders.amount",
        "change_type": "COLUMN_TYPE_CHANGED",
        "before_state": {},
        "after_state": {},
    }
    impacts: List[Dict[str, Any]] = [
        {
            "object": "report_sales",
            "object_type": "VIEW",
            "impact_level": "INDIRECT",
            "depth": 2,
        },
    ]
    context = {
        "source_system": "test-system",
        "snapshot_time": datetime(2024, 1, 1, tzinfo=UTC).isoformat(),
    }
    return change_event, impacts, context


def test_taisa_client_can_be_instantiated() -> None:
    client = TaisaClient()
    assert isinstance(client, TaisaClient)
    assert isinstance(client.config, TaisaClientConfig)


def test_analyze_change_requires_all_named_arguments() -> None:
    client = TaisaClient()
    change_event, impacts, context = _make_minimal_input()

    # Missing any of the required keyword-only arguments should raise
    # a TypeError at call time.
    try:
        client.analyze_change(change_event=change_event, impacts=impacts)  # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError("Expected TypeError when context is missing")

    # Passing None for any of the arguments should raise ValueError.
    for bad_change_event in (None,):
        try:
            client.analyze_change(
                change_event=bad_change_event,  # type: ignore[arg-type]
                impacts=impacts,
                context=context,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Expected ValueError when change_event is None")

    for bad_impacts in (None,):
        try:
            client.analyze_change(
                change_event=change_event,
                impacts=bad_impacts,  # type: ignore[arg-type]
                context=context,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Expected ValueError when impacts is None")

    for bad_context in (None,):
        try:
            client.analyze_change(
                change_event=change_event,
                impacts=impacts,
                context=bad_context,  # type: ignore[arg-type]
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Expected ValueError when context is None")


def test_taisa_client_has_no_persistence_side_effects() -> None:
    """Calling TaisaClient must not change DB state.

    The client itself does not import DB models; this test uses DB models
    only to assert that invoking the client leaves persistent state
    unchanged.
    """

    _reset_state()

    with Session(engine) as session:
        snap_before = session.query(Snapshot).count()
        change_before = session.query(ChangeEvent).count()
        node_before = session.query(GraphNode).count()
        impact_before = session.query(ImpactEvent).count()

    client = TaisaClient()
    change_event, impacts, context = _make_minimal_input()

    result = client.analyze_change(
        change_event=change_event,
        impacts=impacts,
        context=context,
    )

    # Correlation fields may be None for the normalised payload.
    assert result.change_id is None
    assert result.snapshot_id is None

    # Response model (v7.5) must be fully populated and correctly typed.
    assert isinstance(result.classification, str) and result.classification
    assert isinstance(result.risk_level, str) and result.risk_level
    assert isinstance(result.recommendations, list)
    assert all(isinstance(r, str) for r in result.recommendations)
    assert isinstance(result.explanation, str) and result.explanation

    # Raw payload is present for audit/debug.
    assert isinstance(result.summary, str)
    assert "request" in result.raw_response

    with Session(engine) as session:
        snap_after = session.query(Snapshot).count()
        change_after = session.query(ChangeEvent).count()
        node_after = session.query(GraphNode).count()
        impact_after = session.query(ImpactEvent).count()

    assert snap_before == snap_after
    assert change_before == change_after
    assert node_before == node_after
    assert impact_before == impact_after


def test_taisa_client_is_replaceable_with_fake_implementation() -> None:
    """The system must be able to swap TaisaClient with a fake/mock.

    This test exercises duck-typing: any subclass implementing
    analyze_change with the same contract should be usable.
    """

    class FakeTaisaClient(TaisaClient):
        def analyze_change(  # type: ignore[override]
            self,
            *,
            change_event: Dict[str, Any],
            impacts: List[Dict[str, Any]],
            context: Dict[str, Any],
        ) -> Any:
            return {
                "kind": "fake-taisa-response",
                "change_id": change_event.get("change_id"),
                # Use the normalised impact payload (object identifier), not
                # internal node IDs.
                "impacted": [i["object"] for i in impacts],
                "snapshot_id": context.get("snapshot_id"),
            }

    fake_client = FakeTaisaClient()
    change_event, impacts, context = _make_minimal_input()

    response = fake_client.analyze_change(
        change_event=change_event,
        impacts=impacts,
        context=context,
    )

    assert response["kind"] == "fake-taisa-response"
    assert response["change_id"] is None
    assert response["snapshot_id"] is None
    assert response["impacted"] == [i["object"] for i in impacts]


def test_invalid_impact_level_is_rejected() -> None:
    client = TaisaClient()
    change_event, impacts, context = _make_minimal_input()
    impacts[0]["impact_level"] = "UNKNOWN"  # invalid

    try:
        client.analyze_change(
            change_event=change_event,
            impacts=impacts,
            context=context,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Expected ValueError for invalid impact_level")


def test_before_after_state_must_be_json_serialisable() -> None:
    client = TaisaClient()
    change_event, impacts, context = _make_minimal_input()

    # Use a non-serialisable type (set) in before_state.
    change_event["before_state"] = {1, 2, 3}  # type: ignore[assignment]

    try:
        client.analyze_change(
            change_event=change_event,
            impacts=impacts,
            context=context,
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Expected ValueError when before_state is not JSON-serialisable"
        )


def test_request_is_json_serialisable_and_includes_prompt_contract_version() -> None:
    change_event, impacts, context = _make_minimal_input()

    request = TaisaAnalysisRequest.from_raw(
        prompt_version=PROMPT_CONTRACT_VERSION,
        change_event=change_event,
        impacts=impacts,
        context=context,
    )

    primitive = request.to_primitive()

    assert primitive["prompt_version"] == PROMPT_CONTRACT_VERSION
    # Ensure the whole structure is JSON-serialisable.
    json.dumps(primitive)
