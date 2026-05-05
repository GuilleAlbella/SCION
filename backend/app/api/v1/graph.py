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

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.graph.graph_models import GraphEdge, GraphNode


router = APIRouter(prefix="/graph", tags=["graph"])


# Soft cap on the full-graph endpoint. Above this we refuse to serialise
# the snapshot — the browser can't dagre-layout that many nodes anyway,
# and we don't want to ship tens of MB just for the frontend to throw
# them away. Tuned generously (5k) so the demo and small-customer
# workloads keep the existing "see everything at once" UX. Above this,
# the frontend should fall back to the focus picker (driven by
# ``/objects/search?source=graph``).
FULL_GRAPH_NODE_CAP = 5000


# Hard cap on focus subgraph size. Used to bound BFS even when the
# caller asks for more — pathologically dense neighbourhoods can
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
    # the empty-state message ("This graph has 337k nodes — pick an
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
    # of more — increase max_nodes or narrow the search" affordance.
    capped: bool


# IMPORTANT: route ORDER matters here. FastAPI matches in source order,
# so the static ``/focus`` route MUST come before the ``/{snapshot_id}``
# parametrised route — otherwise ``GET /focus`` is routed to
# ``get_graph`` which tries to parse the literal string "focus" as
# ``snapshot_id: int`` and rejects it with 422 Unprocessable Entity.
# (Yes, we hit this bug on the first /lineage call against Transcend.)


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
    """Server-side BFS around an anchor — bounded subgraph for visualisation.

    Why this exists
    ---------------
    The full-graph endpoint returns hundreds of MB on a Transcend extract,
    and even after the wire transfer the browser has to run dagre's
    O(V³) hierarchical layout over it. The historical client-side
    "focus mode" carved out the subgraph in the browser — but that
    required loading the entire graph first, defeating the purpose.
    This endpoint moves the BFS to the server, returns ~200 nodes, and
    keeps both the wire and the layout cheap.

    Behaviour
    ---------
    1. Resolve ``root`` → ``node_id``. We try exact match on
       ``(schema_name, object_name)`` after splitting on the first dot;
       fall back to ``object_name`` equality so callers can pass an
       unqualified name (matches the legacy ``ObjectPicker`` behaviour).
       404 if neither yields a row.
    2. BFS up to ``hops`` deep. Each hop runs a single SQL query for
       all edges touching the current frontier — fast given the
       ``ix_graph_edge_snapshot`` index.
    3. Stop early when ``max_nodes`` is reached. Surface that as
       ``capped: true`` so the UI can warn the user.
    4. Edges are deduplicated and only emitted when both endpoints
       made it into the visited set (avoids dangling-endpoint errors
       in React Flow).

    Edge type and direction filters are applied during traversal, so
    they affect both *which* nodes are reached AND which edges are
    rendered — i.e. ``direction=down`` returns the downstream subgraph,
    not the full neighbourhood with downstream-only edges drawn.
    """

    edge_type_set: Optional[set[str]] = None
    if edge_types and edge_types.strip():
        edge_type_set = {t.strip().upper() for t in edge_types.split(",") if t.strip()}

    with Session(bind=engine) as session:
        # ──── Step 1: resolve root → graph_node_id ────
        root_node = _resolve_root(session, snapshot_id, root)
        if root_node is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No graph_node found for root={root!r} in snapshot {snapshot_id}.",
            )

        # ──── Step 2: BFS ────
        visited_ids: set[int] = {root_node.node_id}
        frontier: set[int] = {root_node.node_id}
        edges_collected: list[GraphEdge] = []
        capped = False

        for _ in range(hops):
            if not frontier or len(visited_ids) >= max_nodes:
                break

            # Edges touching the current frontier, filtered by direction
            # and edge type. We split into source-or-target conditions
            # so the planner can use the (snapshot_id) index on each
            # branch independently. ``in_(frontier)`` is fine for our
            # max_nodes range (<=1000).
            conds = []
            if direction in ("down", "both"):
                conds.append(GraphEdge.source_node_id.in_(frontier))
            if direction in ("up", "both"):
                conds.append(GraphEdge.target_node_id.in_(frontier))
            edges_q = (
                select(GraphEdge)
                .where(GraphEdge.snapshot_id == snapshot_id)
                .where(or_(*conds))
            )
            if edge_type_set:
                # ``relationship_type`` is the legacy column; ``edge_type``
                # is the post-1.04 nullable column. Match either.
                edges_q = edges_q.where(
                    or_(
                        GraphEdge.edge_type.in_(edge_type_set),
                        GraphEdge.relationship_type.in_(edge_type_set),
                    )
                )

            hop_edges = session.execute(edges_q).scalars().all()

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

        # ──── Step 3: load full node rows for visited set ────
        node_rows = []
        if visited_ids:
            node_rows = session.execute(
                select(GraphNode).where(GraphNode.node_id.in_(visited_ids))
            ).scalars().all()

    # ──── Step 4: serialize, dedupe edges, filter dangling ────
    nodes, edges = _serialize_graph(node_rows, edges_collected, restrict_to_ids=visited_ids)

    return {
        "snapshot_id": snapshot_id,
        "root": root,
        "hops": hops,
        "max_nodes": max_nodes,
        "nodes": nodes,
        "edges": edges,
        "capped": capped,
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

    with Session(bind=engine) as session:
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

    nodes, edges = _serialize_graph(node_rows, edge_rows)
    return {
        "snapshot_id": snapshot_id,
        "nodes": nodes,
        "edges": edges,
        "truncated": False,
        "total_nodes": total_nodes,
    }


# ──── Helpers ────


def _resolve_root(session: Session, snapshot_id: int, root: str) -> Optional[GraphNode]:
    """Find a ``GraphNode`` whose identifier matches ``root``.

    We accept two encodings (in order):

    1. ``schema.object_name`` — split on the FIRST dot. Matches the
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
            (GraphNode.schema_name == schema_part)
            & (GraphNode.object_name == object_part)
        )
    conds.append(GraphNode.object_name == root)
    candidates_q = candidates_q.where(or_(*conds)).limit(1)

    return session.execute(candidates_q).scalars().first()


def _serialize_graph(
    node_rows,
    edge_rows,
    restrict_to_ids: Optional[set[int]] = None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Project ORM rows into the {node_id, ...} JSON shape used by both endpoints.

    ``restrict_to_ids`` is the BFS visited set for the focus path — we
    drop edges whose endpoints didn't make it into the subgraph and
    deduplicate edges that BFS traversed from both directions.
    """
    uid_by_id: Dict[int, str] = {
        row.node_id: row.node_uid or str(row.node_id) for row in node_rows
    }

    nodes: List[Dict[str, Any]] = [
        {
            "node_id": row.node_uid or str(row.node_id),
            "object_type": row.object_type,
            "object_name": row.object_name,
            "schema_name": row.schema_name,
            "metrics": row.node_metadata,
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
