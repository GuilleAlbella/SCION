from __future__ import annotations

from typing import Dict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent
from app.graph.graph_models import GraphNode


def link_changes_to_graph(snapshot_to: int) -> Dict[int, int]:
    """Link change_event rows to graph_node rows for a given snapshot.

    The function is **read-only** and **idempotent**:

    - It does not write to the database.
    - It does not modify existing rows.
    - It uses only ``snapshot_to`` to resolve links.

    Returns:
+        Dict[int, int]: mapping ``change_id -> graph_node_id`` for
+        successfully resolved events.
    """

    if snapshot_to is None:
        raise ValueError("snapshot_to must not be None")

    with Session(engine) as session:
        return _link_changes_to_graph_in_session(session, snapshot_to)


def _link_changes_to_graph_in_session(
    session: Session, snapshot_to: int
) -> Dict[int, int]:
    """Internal helper that performs the actual resolution.

    Assumes a read-only use of the provided session.
    """

    # ──── Step 1: Load every ChangeEvent targeting this snapshot ────
    # We filter by snapshot_to because a change "arrives" at the post-state
    # snapshot — that's where the corresponding GraphNode lives.
    # Load all change events for the target snapshot.
    change_events = session.scalars(
        select(ChangeEvent).where(ChangeEvent.snapshot_to == snapshot_to)
    ).all()

    if not change_events:
        return {}

    # ──── Step 2: Index graph nodes by natural key ────
    # The natural key (object_type, object_name, snapshot_id) is what both
    # ChangeEvent and GraphNode share — the synthetic primary keys differ.
    # Load all graph nodes for the same snapshot and index them by their
    # natural key (object_type, object_name, snapshot_id).
    nodes = session.scalars(
        select(GraphNode).where(GraphNode.snapshot_id == snapshot_to)
    ).all()

    nodes_by_key: Dict[tuple[str, str, int], int] = {}
    # Secondary index by object_name alone — used as fallback when the
    # (object_type, name) lookup fails. Needed for COLUMN changes: the
    # change has object_type="COLUMN" and identifier "db.tbl.col", but
    # the graph only contains the parent table node under type TABLE/VIEW.
    nodes_by_name: Dict[str, int] = {}

    for node in nodes:
        # Keys are lowercased so ChangeEvent identifiers from PDCR (UPPERCASE)
        # and dict snapshots (mixed case) resolve to the same node.
        key = (node.object_type, node.object_name.lower(), node.snapshot_id)
        if key in nodes_by_key:
            # Multiple nodes with the same natural key represent an invalid
            # state for linking; fail explicitly.
            raise RuntimeError(
                "Multiple graph_node rows match the same natural key: "
                f"{key!r}"
            )
        nodes_by_key[key] = node.node_id
        nodes_by_name[node.object_name.lower()] = node.node_id

    # ──── Step 3: Join change events to node ids ────
    # Two-stage resolution: exact (type, name) match first; if that
    # misses and the change looks column-scoped, fall back to the parent
    # table's node. The fallback makes column-level changes participate
    # in impact analysis via their host table — which is the correct
    # propagation semantics anyway (a column type change ripples to any
    # view/proc that SELECTs that column, i.e. the table's consumers).
    mapping: Dict[int, int] = {}

    for event in change_events:
        key = (event.object_type, (event.object_identifier or "").lower(), snapshot_to)
        node_id = nodes_by_key.get(key)

        if node_id is None:
            # Fallback for COLUMN_* changes: identifier is "db.tbl.col";
            # strip the last segment to get "db.tbl" and look it up by
            # name alone (it could be TABLE, VIEW, or even a procedural
            # object — any is valid as a propagation anchor).
            if event.object_type == "COLUMN":
                parts = (event.object_identifier or "").rsplit(".", 1)
                if len(parts) == 2:
                    parent_name = parts[0].lower()
                    node_id = nodes_by_name.get(parent_name)

        if node_id is None:
            # Final fallback: name-only lookup ignoring object_type.
            # Needed when the lineage importer creates graph_node rows
            # with object_type='UNKNOWN' while the diff has the proper
            # type (e.g. 'TABLE'). The exact (type, name) key misses, but
            # the node IS there under a different type label.
            name_lower = (event.object_identifier or "").lower()
            node_id = nodes_by_name.get(name_lower)

        if node_id is None:
            # Still unmapped — object doesn't exist in the graph at all
            # (e.g. truly removed and not present in snapshot_to).
            continue

        mapping[event.change_id] = node_id

    return mapping
