"""Pre-computed proactive structural alerts.

The ``GET /alerts`` endpoint surfaces three structural checks (broken
lineage edges, orphan objects, hub-node changes) on top of the
graph_node / graph_edge tables. Until v1.19 those checks ran inline
on every request: load all nodes + edges for the snapshot (337k+
rows on Transcend), then walk in Python. That's catastrophic on every
page visit.

This module computes the same three checks ONCE during post-ingest,
persists the alerts into ``proactive_alert``, and lets ``/alerts``
read indexed rows. Every check has a hard cap on output rows
(matching the previous in-request slicing of [:15] / [:10]) so the
table stays small even on dense graphs.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Dict, List, Tuple

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.diff.diff_models import ChangeEvent
from app.graph.graph_models import GraphEdge, GraphNode


logger = logging.getLogger(__name__)


# Per-check caps mirror the previous in-request slicing so the alerts
# panel stays compact even on hub-heavy snapshots. Tweak together with
# the request endpoint's overall ``limit`` if we ever surface more.
BROKEN_LINEAGE_CAP = 15
ORPHAN_CAP = 10
HUB_CHANGE_CAP = 10


def _build_node_lookup(
    nodes,
) -> Tuple[Dict[int, str], set]:
    """Return ``(name_by_id, all_node_ids)`` for the given GraphNode rows."""
    name_by_id = {
        n.node_id: f"{n.schema_name}.{n.object_name}"
        if n.schema_name
        else n.object_name
        for n in nodes
    }
    return name_by_id, set(name_by_id.keys())


def compute_proactive_alerts_for_snapshot(snapshot_id: int) -> List[Dict]:
    """Run the three proactive checks and return ready-to-persist dicts.

    Returns rows in the shape ``proactive_alert`` expects, ready for
    bulk-insert. The function is purely computational â€” persistence
    happens in ``persist_proactive_alerts`` so callers can plug into
    their own session/transaction lifecycle.
    """
    with Session(engine) as session:
        snap = session.get(Snapshot, snapshot_id)
        if snap is None:
            return []
        snap_ts = snap.snapshot_time.isoformat() if snap.snapshot_time else ""

        nodes = session.execute(
            select(GraphNode).where(GraphNode.snapshot_id == snapshot_id)
        ).scalars().all()
        edges = session.execute(
            select(GraphEdge).where(GraphEdge.snapshot_id == snapshot_id)
        ).scalars().all()

        # â”€â”€â”€â”€ Check 1: broken lineage â”€â”€â”€â”€
        # An edge pointing to a node that no longer exists in this
        # snapshot is a silent data-quality problem (something was
        # deleted without cleaning up references). We surface up to
        # ``BROKEN_LINEAGE_CAP`` of them.
        name_by_id, all_node_ids = _build_node_lookup(nodes)
        broken: List[Tuple[str, int, int]] = []
        for e in edges:
            if e.source_node_id not in all_node_ids:
                broken.append(("source", e.source_node_id, e.target_node_id))
            elif e.target_node_id not in all_node_ids:
                broken.append(("target", e.source_node_id, e.target_node_id))
            if len(broken) >= BROKEN_LINEAGE_CAP:
                break

        results: List[Dict] = []
        for side, src, tgt in broken[:BROKEN_LINEAGE_CAP]:
            missing = src if side == "source" else tgt
            anchor = tgt if side == "source" else src
            results.append({
                "snapshot_id": snapshot_id,
                "alert_type": "BROKEN_LINEAGE",
                "severity": "HIGH",
                "message": (
                    f"Broken lineage: edge references missing node (id={missing})"
                ),
                "object_identifier": name_by_id.get(anchor, f"node:{missing}"),
                "detected_at_iso": snap_ts,
            })

        # â”€â”€â”€â”€ Check 2: orphan objects â”€â”€â”€â”€
        # Tables / views with no incoming or outgoing edges. SCHEMAs are
        # excluded because they're container nodes; their connectivity
        # is structural rather than data-flow.
        connected_nodes: set = set()
        for e in edges:
            connected_nodes.add(e.source_node_id)
            connected_nodes.add(e.target_node_id)

        orphans = [
            n
            for n in nodes
            if n.node_id not in connected_nodes
            and n.object_type not in ("SCHEMA", "DATABASE")
        ]
        for n in orphans[:ORPHAN_CAP]:
            results.append({
                "snapshot_id": snapshot_id,
                "alert_type": "ORPHAN_OBJECT",
                "severity": "MEDIUM",
                "message": (
                    "Orphan object â€” no upstream or downstream dependencies detected"
                ),
                "object_identifier": name_by_id.get(n.node_id, n.object_name),
                "detected_at_iso": snap_ts,
            })

        # â”€â”€â”€â”€ Check 3: hub-node changes â”€â”€â”€â”€
        # A "hub" is a node flagged ``is_hub`` in its metrics metadata
        # (see ``persist_node_metrics``). Cross-referencing recent
        # ChangeEvents against the hub list flags hub-touching changes
        # for extra scrutiny â€” they have outsized blast-radius.
        hub_node_ids = {
            n.node_id
            for n in nodes
            if (n.node_metadata or {}).get("is_hub")
        }
        hub_names = {
            name_by_id[nid]
            for nid in hub_node_ids
            if nid in name_by_id
        }

        hub_changes_seen = 0
        recent_changes = session.execute(
            select(ChangeEvent)
            .where(ChangeEvent.snapshot_to == snapshot_id)
            .order_by(desc(ChangeEvent.detected_at))
        ).scalars().all()

        for c in recent_changes:
            if c.object_identifier in hub_names:
                results.append({
                    "snapshot_id": snapshot_id,
                    "alert_type": "HUB_CHANGED",
                    "severity": "HIGH",
                    "message": (
                        "Hub node changed â€” high-connectivity object was modified"
                    ),
                    "object_identifier": c.object_identifier,
                    "detected_at_iso": (
                        c.detected_at.isoformat() if c.detected_at else snap_ts
                    ),
                })
                hub_changes_seen += 1
                if hub_changes_seen >= HUB_CHANGE_CAP:
                    break

    return results


def persist_proactive_alerts(snapshot_id: int) -> int:
    """Compute and persist proactive alerts for a snapshot.

    Idempotent: deletes any existing rows for the same snapshot first
    so re-running (after a graph rebuild, for example) replaces stale
    entries instead of compounding them.

    Returns the number of alerts persisted.
    """
    # Late import: ``ProactiveAlert`` lives next to the existing
    # ImpactEvent / ChangeImpactSummary models. Lazy-loading keeps this
    # module importable from contexts that haven't pulled in the model
    # registry yet (mostly an issue for one-off tools).
    from app.graph.impact_models import ProactiveAlert

    rows = compute_proactive_alerts_for_snapshot(snapshot_id)
    now = datetime.now(UTC)
    for row in rows:
        row["computed_at"] = now
        # ``detected_at_iso`` is what the API returns; in the table we
        # store a real DateTime so future endpoints can sort/filter on
        # it. Drop the iso variant before insert.
        row.pop("detected_at_iso", None)

    with Session(engine) as session:
        session.execute(
            delete(ProactiveAlert).where(
                ProactiveAlert.snapshot_id == snapshot_id
            )
        )
        if rows:
            session.bulk_insert_mappings(ProactiveAlert, rows)
        session.commit()

    logger.info(
        "[proactive-alerts] persisted %d row(s) for snapshot %d",
        len(rows),
        snapshot_id,
    )
    return len(rows)
