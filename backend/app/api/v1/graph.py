from __future__ import annotations

"""Graph API (v1).

Read-only access to the structural system graph for a given snapshot.
Two endpoints:

- ``GET /graph/{snapshot_id}`` returns the *full* graph for small
  snapshots, or a truncation marker when the graph would exceed
  ``FULL_GRAPH_NODE_CAP`` nodes (which is what would lock up the
  browser running dagre over a 337k-node Transcend extract).

- ``GET /graph/focus`` returns a server-side BFS subgraph anchored on
  one object, capped at ``max_nodes`` (default 200, hard max 1000).
  Used by Lineage on every fetch and by Graph when the full view is
  too large.
"""

import json as _json
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.graph.graph_models import GraphEdge, GraphNode


router = APIRouter(prefix="/graph", tags=["graph"])


# Soft cap on the full-graph endpoint. Above this we refuse to serialise
# the snapshot â€" the browser can't dagre-layout that many nodes anyway,
# and we don't want to ship tens of MB just for the frontend to throw
# them away. Tuned generously (5k) so the demo and small-customer
# workloads keep the existing "see everything at once" UX. Above this,
# the frontend should fall back to the focus picker (driven by
# ``/objects/search?source=graph``).
FULL_GRAPH_NODE_CAP = 5000


# Hard cap on focus subgraph size. Used to bound BFS even when the
# caller asks for more â€" pathologically dense neighbourhoods can
# explode quickly even at hops=2 ("hub" tables connect to thousands).
FOCUS_GRAPH_HARD_CAP = 1000


class GraphNodeItem(BaseModel):
    node_id: str
    object_type: str
    object_name: str
    schema_name: str
    metrics: Optional[Dict[str, Any]] = None


class GraphEdgeItem(BaseModel):
    source: str
    target: str
    type: str


class GraphResponse(BaseModel):
    snapshot_id: int
    nodes: List[GraphNodeItem]
    edges: List[GraphEdgeItem]
    # When True, the full graph exceeded ``FULL_GRAPH_NODE_CAP`` and we
    # bailed without returning rows. The frontend should switch to the
    # focus picker UX. ``total_nodes`` is the actual count, surfaced for
    # the empty-state message ("This graph has 337k nodes â€" pick an
    # anchor to focus on").
    truncated: bool = False
    total_nodes: int = 0


class FocusedGraphResponse(BaseModel):
    snapshot_id: int
    root: str
    hops: int
    max_nodes: int
    nodes: List[GraphNodeItem]
    edges: List[GraphEdgeItem]
    # True when BFS hit ``max_nodes`` before exhausting the requested
    # hop count. The frontend uses this to surface a "showing first N
    # of more â€" increase max_nodes or narrow the search" affordance.
    capped: bool


class GraphMetaResponse(BaseModel):
    """2.7 Lazy graph fetch -- lightweight COUNT-only response.

    Returned by GET /graph/{snapshot_id}/meta. Contains only counts;
    no nodes or edges are fetched. The frontend uses this to decide whether
    to auto-load the full graph (below LAZY_GRAPH_THRESHOLD) or show a
    'Load Graph (N nodes)' button so the user explicitly triggers the
    potentially-slow full fetch.
    """
    snapshot_id: int
    total_nodes: int
    total_edges: int


# IMPORTANT: route ORDER matters here. FastAPI matches in source order,
# so the static ``/focus`` route MUST come before the ``/{snapshot_id}``
# parametrised route â€" otherwise ``GET /focus`` is routed to
# ``get_graph`` which tries to parse the literal string "focus" as
# ``snapshot_id: int`` and rejects it with 422 Unprocessable Entity.
# (Yes, we hit this bug on the first /lineage call against Transcend.)
# ``GET /graph/{snapshot_id}/meta`` is a sub-path route and also must
# appear before ``/{snapshot_id}`` so FastAPI routes it correctly.


@router.get(
    "/focus",
    status_code=status.HTTP_200_OK,
    response_model=FocusedGraphResponse,
)
def get_focused_graph(
    snapshot_id: int = Query(..., description="Snapshot to traverse."),
    root: str = Query(
        ...,
        description=(
            "Root object identifier as `schema.object_name`. The endpoint "
            "first looks up by exact `(schema_name, object_name)` split on "
            "the first dot; falls back to matching the full string against "
            "`object_name` so legacy callers that pass an unqualified name "
            "still work."
        ),
    ),
    hops: int = Query(2, ge=1, le=5, description="BFS depth from the root."),
    max_nodes: int = Query(
        200,
        ge=10,
        le=FOCUS_GRAPH_HARD_CAP,
        description="Hard cap on returned nodes. BFS stops when reached.",
    ),
    edge_types: Optional[str] = Query(
        None,
        description=(
            "Comma-separated list of edge types to traverse "
            "(e.g. `FEEDS,DEPENDS_ON`). Empty / null means all types."
        ),
    ),
    direction: Literal["up", "down", "both"] = Query(
        "both",
        description=(
            "`up` = follow edges where root is the target (incoming). "
            "`down` = follow edges where root is the source (outgoing). "
            "`both` = undirected BFS (the default; matches the existing "
            "Lineage page logic)."
        ),
    ),
) -> Dict[str, Any]:
    """Server-side BFS around an anchor â€" bounded subgraph for visualisation.

    Why this exists
    ---------------
    The full-graph endpoint returns hundreds of MB on a Transcend extract,
    and even after the wire transfer the browser has to run dagre's
    O(VÂ³) hierarchical layout over it. The historical client-side
    "focus mode" carved out the subgraph in the browser â€" but that
    required loading the entire graph first, defeating the purpose.
    This endpoint moves the BFS to the server, returns ~200 nodes, and
    keeps both the wire and the layout cheap.

    Behaviour
    ---------
    1. Resolve ``root`` â†' ``node_id``. We try exact match on
       ``(schema_name, object_name)`` after splitting on the first dot;
       fall back to ``object_name`` equality so callers can pass an
       unqualified name (matches the legacy ``ObjectPicker`` behaviour).
       404 if neither yields a row.
    2. BFS up to ``hops`` deep. Each hop runs a single SQL query for
       all edges touching the current frontier â€" fast given the
       ``ix_graph_edge_snapshot`` index.
    3. Stop early when ``max_nodes`` is reached. Surface that as
       ``capped: true`` so the UI can warn the user.
    4. Edges are deduplicated and only emitted when both endpoints
       made it into the visited set (avoids dangling-endpoint errors
       in React Flow).

    Edge type and direction filters are applied during traversal, so
    they affect both *which* nodes are reached AND which edges are
    rendered â€" i.e. ``direction=down`` returns the downstream subgraph,
    not the full neighbourhood with downstream-only edges drawn.
    """

    edge_type_set: Optional[set[str]] = None
    if edge_types and edge_types.strip():
        edge_type_set = {t.strip().upper() for t in edge_types.split(",") if t.strip()}

    with Session(engine) as session:
        # â"€â"€â"€â"€ Step 1: resolve root â†' graph_node_id â"€â"€â"€â"€
        root_node = _resolve_root(session, snapshot_id, root)
        if root_node is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No graph_node found for root={root!r} in snapshot {snapshot_id}.",
            )

        # â"€â"€â"€â"€ Step 2: BFS â"€â"€â"€â"€
        visited_ids: set[int] = {root_node.node_id}
        frontier: set[int] = {root_node.node_id}
        edges_collected: list[GraphEdge] = []
        capped = False

        for _ in range(hops):
            if not frontier or len(visited_ids) >= max_nodes:
                break

            hop_limit = max_nodes * 10

            if direction == "both":
                # §2.6 Graph engine perf: issue two separate queries so the
                # planner can use ix_graph_edge_snapshot_source for the "down"
                # leg and ix_graph_edge_snapshot_target for the "up" leg.
                # A single OR across both columns forces the planner onto the
                # weaker ix_graph_edge_snapshot index with a post-filter pass.
                def _edge_q(col_cond):
                    q = (
                        select(GraphEdge)
                        .where(GraphEdge.snapshot_id == snapshot_id)
                        .where(col_cond)
                    )
                    if edge_type_set:
                        q = q.where(
                            or_(
                                GraphEdge.edge_type.in_(edge_type_set),
                                GraphEdge.relationship_type.in_(edge_type_set),
                            )
                        )
                    return q

                raw_down = session.execute(
                    _edge_q(GraphEdge.source_node_id.in_(frontier)).limit(hop_limit)
                ).scalars().all()
                raw_up = session.execute(
                    _edge_q(GraphEdge.target_node_id.in_(frontier)).limit(hop_limit)
                ).scalars().all()

                # Deduplicate: an edge where both endpoints are in the frontier
                # would appear in both result sets.
                seen_eids: set[int] = set()
                hop_edges: list[GraphEdge] = []
                for e in (*raw_down, *raw_up):
                    if e.edge_id not in seen_eids:
                        seen_eids.add(e.edge_id)
                        hop_edges.append(e)
            else:
                # Single-direction: one query, one composite index.
                col_cond = (
                    GraphEdge.source_node_id.in_(frontier)
                    if direction == "down"
                    else GraphEdge.target_node_id.in_(frontier)
                )
                edges_q = (
                    select(GraphEdge)
                    .where(GraphEdge.snapshot_id == snapshot_id)
                    .where(col_cond)
                )
                if edge_type_set:
                    edges_q = edges_q.where(
                        or_(
                            GraphEdge.edge_type.in_(edge_type_set),
                            GraphEdge.relationship_type.in_(edge_type_set),
                        )
                    )
                hop_edges = session.execute(edges_q.limit(hop_limit)).scalars().all()

            next_frontier: set[int] = set()
            for edge in hop_edges:
                edges_collected.append(edge)
                # Determine which endpoint is "new" relative to visited.
                for endpoint in (edge.source_node_id, edge.target_node_id):
                    if endpoint in visited_ids:
                        continue
                    if len(visited_ids) >= max_nodes:
                        capped = True
                        break
                    visited_ids.add(endpoint)
                    next_frontier.add(endpoint)
                if capped:
                    break

            if capped or not next_frontier:
                break
            frontier = next_frontier

        # â"€â"€â"€â"€ Step 3: load full node rows for visited set â"€â"€â"€â"€
        node_rows = []
        if visited_ids:
            node_rows = session.execute(
                select(GraphNode).where(GraphNode.node_id.in_(visited_ids))
            ).scalars().all()
        type_lookup = _build_type_lookup(session, snapshot_id)

    # ──── Step 4: serialize, dedupe edges, filter dangling ────
    nodes, edges = _serialize_graph(node_rows, edges_collected, restrict_to_ids=visited_ids, type_lookup=type_lookup)

    return {
        "snapshot_id": snapshot_id,
        "root": root,
        "hops": hops,
        "max_nodes": max_nodes,
        "nodes": nodes,
        "edges": edges,
        "capped": capped,
    }


@router.get(
    "/{snapshot_id}/meta",
    status_code=status.HTTP_200_OK,
    response_model=GraphMetaResponse,
)
def get_graph_meta(snapshot_id: int) -> Dict[str, Any]:
    """2.7 Lazy graph fetch -- COUNT-only probe, no node/edge data transferred.

    Called by the frontend before deciding whether to auto-load the full graph.
    Two SELECT COUNT(*) queries hit the snapshot indexes and return in
    sub-milliseconds even on 337k-node extracts. The frontend compares
    total_nodes against its own LAZY_GRAPH_THRESHOLD (500) to decide:
    below -- auto-load; at/above -- show a 'Load Graph (N nodes)' button.
    """
    with Session(engine) as session:
        total_nodes = int(
            session.execute(
                select(func.count())
                .select_from(GraphNode)
                .where(GraphNode.snapshot_id == snapshot_id)
            ).scalar_one()
            or 0
        )
        total_edges = int(
            session.execute(
                select(func.count())
                .select_from(GraphEdge)
                .where(GraphEdge.snapshot_id == snapshot_id)
            ).scalar_one()
            or 0
        )
    return {
        "snapshot_id": snapshot_id,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
    }


@router.get("/{snapshot_id}", status_code=status.HTTP_200_OK, response_model=GraphResponse)
def get_graph(snapshot_id: int) -> Dict[str, Any]:
    """Return the full structural graph for a snapshot, or a truncation marker.

    For graphs at or below ``FULL_GRAPH_NODE_CAP`` nodes the response is
    the full set of nodes + edges (matches the pre-v1.17 behaviour so
    the demo and small customers see no UX change). Above the cap we
    return ``{ truncated: true, total_nodes: N, nodes: [], edges: [] }``
    and the frontend switches to the focus-picker flow rather than
    locking up the browser.
    """

    with Session(engine) as session:
        # Cheap pre-flight count first. With the
        # ``ix_graph_node_snapshot`` index this is sub-millisecond even
        # on 337k-node extracts; doing it before the bulk fetch saves
        # us from materialising millions of rows we'd then discard.
        total_nodes = int(
            session.execute(
                select(func.count())
                .select_from(GraphNode)
                .where(GraphNode.snapshot_id == snapshot_id)
            ).scalar_one()
            or 0
        )

        if total_nodes > FULL_GRAPH_NODE_CAP:
            return {
                "snapshot_id": snapshot_id,
                "nodes": [],
                "edges": [],
                "truncated": True,
                "total_nodes": total_nodes,
            }

        node_rows = session.execute(
            select(GraphNode).where(GraphNode.snapshot_id == snapshot_id)
        ).scalars().all()
        edge_rows = session.execute(
            select(GraphEdge).where(GraphEdge.snapshot_id == snapshot_id)
        ).scalars().all()
        type_lookup = _build_type_lookup(session, snapshot_id)

    nodes, edges = _serialize_graph(node_rows, edge_rows, type_lookup=type_lookup)
    return {
        "snapshot_id": snapshot_id,
        "nodes": nodes,
        "edges": edges,
        "truncated": False,
        "total_nodes": total_nodes,
    }


# â"€â"€â"€â"€ Helpers â"€â"€â"€â"€


def _resolve_root(session: Session, snapshot_id: int, root: str) -> Optional[GraphNode]:
    """Find a ``GraphNode`` whose identifier matches ``root``.

    We accept two encodings (in order):

    1. ``schema.object_name`` â€" split on the FIRST dot. Matches the
       output of ``/objects/search?source=graph``, which is what the
       autocomplete component sends.
    2. The raw ``root`` string against ``object_name`` directly.
       Some legacy callers (and SCION's own ``ObjectPicker``) pass
       unqualified names; we keep that working.

    Returns ``None`` when neither encoding matches.
    """
    schema_part: Optional[str] = None
    object_part: Optional[str] = None
    if "." in root:
        schema_part, object_part = root.split(".", 1)

    candidates_q = select(GraphNode).where(GraphNode.snapshot_id == snapshot_id)
    conds = []
    if schema_part is not None and object_part is not None:
        conds.append(
            (func.lower(GraphNode.schema_name) == schema_part.lower())
            & (func.lower(GraphNode.object_name) == object_part.lower())
        )
    conds.append(func.lower(GraphNode.object_name) == root.lower())
    candidates_q = candidates_q.where(or_(*conds)).limit(1)

    return session.execute(candidates_q).scalars().first()


def _build_type_lookup(session: Session, snapshot_id: int) -> Dict[str, str]:
    """Return a {SCHEMA.TABLE_NAME (upper): object_type} dict from table_snapshot.

    This is the authoritative source — object_type comes from TablesV.TableKind
    via object_type_from_tablekind() at ingest time.  Used to resolve UNKNOWN
    graph nodes without relying on naming-convention heuristics.
    """
    rows = session.execute(
        select(SchemaSnapshot.schema_name, TableSnapshot.table_name, TableSnapshot.object_type)
        .join(TableSnapshot, TableSnapshot.schema_id == SchemaSnapshot.schema_id)
        .where(SchemaSnapshot.snapshot_id == snapshot_id)
    ).all()
    return {
        f"{schema}.{table}".upper(): otype
        for schema, table, otype in rows
        if otype and otype != "UNKNOWN"
    }


def _resolve_object_type(row, type_lookup: Dict[str, str]) -> str:
    """Resolve the display object_type for a GraphNode row.

    Resolution order (most authoritative first):
      1. The stored object_type if already known (not UNKNOWN).
      2. TablesV.TableKind via type_lookup (dict-import data).
      3. Schema-name heuristic (_VW / _VIEW suffix) as last resort.

    The heuristic is only reached for objects that exist in the lineage
    feed but have no matching entry in the data dictionary — e.g. external
    references or objects dropped before the dict-import ran.
    """
    if row.object_type != "UNKNOWN":
        return row.object_type

    # Only lineage-only nodes have a plain 'SCHEMA.NAME' uid (no colon).
    # Parser-imported UNKNOWN nodes ('UNKNOWN:SCHEMA.NAME:snap_id') keep
    # their UNKNOWN type — they have no dict entry to resolve against.
    if ":" in (row.node_uid or ""):
        return row.object_type

    key = (row.object_name or "").upper()
    if key in type_lookup:
        return type_lookup[key]

    # Fallback: Teradata naming convention (_VW / _VIEW schema suffix).
    schema = (row.schema_name or "").upper()
    if schema.endswith(("_VW", "_VIEW")):
        return "VIEW"
    return "TABLE"


def _serialize_graph(
    node_rows,
    edge_rows,
    type_lookup: Optional[Dict[str, str]] = None,
    restrict_to_ids: Optional[set[int]] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Project ORM rows into the {node_id, ...} JSON shape used by both endpoints.

    ``restrict_to_ids`` is the BFS visited set for the focus path â€" we
    drop edges whose endpoints didn't make it into the subgraph and
    deduplicate edges that BFS traversed from both directions.

    ``type_lookup`` is a {SCHEMA.TABLE (upper): object_type} dict built from
    table_snapshot.  When provided, UNKNOWN nodes are resolved against it
    before falling back to the naming-convention heuristic.
    """
    _lookup = type_lookup or {}
    uid_by_id: Dict[int, str] = {
        row.node_id: row.node_uid or str(row.node_id) for row in node_rows
    }

    nodes: List[Dict[str, Any]] = [
        {
            "node_id": row.node_uid or str(row.node_id),
            "object_type": _resolve_object_type(row, _lookup),
            "object_name": row.object_name,
            "schema_name": row.schema_name,
            "metrics": _json.loads(row.node_metadata) if isinstance(row.node_metadata, str) else row.node_metadata,
        }
        for row in node_rows
    ]

    seen_edge_keys: set[tuple[int, int, str]] = set()
    edges: List[Dict[str, Any]] = []
    for edge in edge_rows:
        if restrict_to_ids is not None and (
            edge.source_node_id not in restrict_to_ids
            or edge.target_node_id not in restrict_to_ids
        ):
            continue
        edge_kind = edge.edge_type or edge.relationship_type or "DEPENDS_ON"
        key = (edge.source_node_id, edge.target_node_id, edge_kind)
        if key in seen_edge_keys:
            continue
        seen_edge_keys.add(key)
        source_uid = edge.from_node_uid or uid_by_id.get(
            edge.source_node_id, str(edge.source_node_id)
        )
        target_uid = edge.to_node_uid or uid_by_id.get(
            edge.target_node_id, str(edge.target_node_id)
        )
        edges.append(
            {
                "source": source_uid,
                "target": target_uid,
                "type": edge_kind,
            }
        )

    return nodes, edges
