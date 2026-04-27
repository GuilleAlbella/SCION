from __future__ import annotations

from typing import Dict, List

from sqlalchemy.orm import Session

from app.db.engine import engine
from app.graph.impact_models import ImpactEvent


def persist_impact_events(
    *,
    change_id: int,
    snapshot_id: int,
    impacts: List[Dict],
) -> None:
    """Persist impact events for a given change and snapshot.

    Behaviour:

    - Uses a single transaction; any failure rolls back all inserts.
    - Is idempotent per (change_id, snapshot_id): if any rows already exist
      for that pair, the function performs no inserts and returns silently.
    - Does not delete or update existing impact events.
    """

    if change_id is None or snapshot_id is None:
        raise ValueError("change_id and snapshot_id must not be None")

    with Session(engine) as session:
        try:
            with session.begin():
                _persist_impact_events_in_session(
                    session=session,
                    change_id=change_id,
                    snapshot_id=snapshot_id,
                    impacts=impacts,
                )
        except Exception:
            session.rollback()
            raise


def _persist_impact_events_in_session(
    *,
    session: Session,
    change_id: int,
    snapshot_id: int,
    impacts: List[Dict],
) -> None:
    # Idempotency check: if any impact_event exists for this pair, do nothing.
    # Rationale: impact analysis is deterministic for a given (change, snapshot),
    # so re-runs would insert identical rows. A single-row probe is faster
    # than SELECT COUNT and sufficient for the yes/no decision.
    existing = (
        session.query(ImpactEvent)
        .filter(
            ImpactEvent.change_id == change_id,
            ImpactEvent.snapshot_id == snapshot_id,
        )
        .first()
    )
    if existing is not None:
        return

    for impact in impacts:
        node_id = impact["node_id"]
        depth = impact["depth"]

        # depth < 1 would indicate a bug in the CTE seed — the start node
        # itself is never returned, so 0 is invalid.
        if depth < 1:
            raise ValueError("depth must be >= 1 for impact events")

        # Two-tier categorical label for UI/reporting. Anything beyond the
        # first hop is lumped as INDIRECT; the raw depth column preserves
        # the fine-grained distance for deeper analysis.
        impact_level = "DIRECT" if depth == 1 else "INDIRECT"

        session.add(
            ImpactEvent(
                change_id=change_id,
                impacted_node_id=node_id,
                impact_level=impact_level,
                depth=depth,
                snapshot_id=snapshot_id,
                impact_score=impact.get("impact_score"),
            )
        )
