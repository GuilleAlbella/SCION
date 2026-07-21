from __future__ import annotations

"""Build the technical lineage graph for a snapshot.

Two design goals are in tension here and both have to be satisfied:

  1. **Correctness / idempotency.** Re-running this for the same
     `snapshot_id` must not create duplicate nodes or edges. This is
     enforced by checking against the set of existing rows we
     pre-load up front (not a unique constraint, because hitting one
     mid-batch would abort the whole transaction in SQLite).

  2. **Scale.** The full Transcend-DevTest extract is 240k+ tables and
     9.8M columns. The original implementation called `session.add()`
     + `session.flush()` per node and ran a per-edge SELECT inside
     `_ensure_edge` — i.e. ~500k DB roundtrips total, each with the
     full SQLAlchemy ORM stack on top. That ran for 30+ minutes
     without finishing. The current implementation collects nodes
     and edges into Python dicts, dedupes them in memory, and ships
     them to the DB in two `bulk_insert_mappings` calls. Same wire
     contract, three orders of magnitude fewer roundtrips.
"""

from typing import Dict, List, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot
from app.graph.graph_models import GraphEdge, GraphNode


# Tuned for SQLite; same logic Postgres would use, just larger batches
# would amortize better there. 5 000 is comfortably below SQLite's
# host-parameter cap (32 766 since 3.32) for the column counts we
# insert (~6 columns per row → ~30 000 host params per batch — fits).
_BULK_INSERT_BATCH_SIZE = 5000


def build_graph_for_snapshot(snapshot_id: int) -> None:
    """Build / refresh the technical lineage graph for a snapshot.

    Idempotent at the (object_type, object_name, snapshot_id) key for
    nodes and the (source, target, relationship_type, snapshot_id) key
    for edges — re-running emits nothing new.

    Creates:
      - SCHEMA nodes
      - TABLE / VIEW nodes with DEPENDS_ON edges to their schema
      - FEEDS edges between tables based on `_id` column-name heuristics
    """

    if snapshot_id is None:
        raise ValueError("snapshot_id must not be None")

    with Session(engine) as session:
        try:
            with session.begin():
                _build_graph_for_snapshot_in_session(session, snapshot_id)
        except Exception:
            session.rollback()
            raise


def _build_graph_for_snapshot_in_session(
    session: Session,
    snapshot_id: int,
) -> None:
    """Internal helper that performs the actual graph construction."""

    # ──── Step 1: Load snapshot metadata ────
    # We pull schemas / tables / columns in three queries (rather than one
    # giant join) so each result row stays narrow. Column rows are by far
    # the heaviest list — for the full Transcend-DevTest extract this is
    # ~9.8M tuples — but they're 3-tuples of strings, so ~700 MB-class
    # memory. Acceptable on any modern dev box; the alternative
    # (streaming + repeated parent lookups) would more than offset that
    # gain.
    schema_rows = session.scalars(
        select(SchemaSnapshot).where(SchemaSnapshot.snapshot_id == snapshot_id)
    ).all()

    table_rows = session.execute(
        select(SchemaSnapshot.schema_name, TableSnapshot)
        .join(TableSnapshot, TableSnapshot.schema_id == SchemaSnapshot.schema_id)
        .where(SchemaSnapshot.snapshot_id == snapshot_id)
    ).all()

    column_rows = session.execute(
        select(
            SchemaSnapshot.schema_name,
            TableSnapshot.table_name,
            ColumnSnapshot.column_name,
        )
        .join(TableSnapshot, TableSnapshot.schema_id == SchemaSnapshot.schema_id)
        .join(ColumnSnapshot, ColumnSnapshot.table_id == TableSnapshot.table_id)
        .where(SchemaSnapshot.snapshot_id == snapshot_id)
    ).all()

    # ──── Step 2: Pre-load existing nodes + edges (idempotency seed) ────
    # One SELECT per relation, into Python dicts/sets. After this we never
    # round-trip back to the DB to "check if row X exists" — every check
    # is a hash lookup. For 240k tables this collapses ~500k SELECT
    # statements into 2.
    existing_nodes_by_key: Dict[Tuple[str, str, int], int] = {}
    existing_node_uids: Dict[int, str] = {}
    for node_id, otype, oname, sid, uid in session.execute(
        select(
            GraphNode.node_id,
            GraphNode.object_type,
            GraphNode.object_name,
            GraphNode.snapshot_id,
            GraphNode.node_uid,
        ).where(GraphNode.snapshot_id == snapshot_id)
    ).all():
        existing_nodes_by_key[(otype, oname, sid)] = node_id
        existing_node_uids[node_id] = uid or ""

    # Set of edge identity tuples already in the DB. We only need the
    # tuple to skip duplicates, not the row data — saves memory.
    existing_edges: Set[Tuple[int, int, str, int]] = set(
        session.execute(
            select(
                GraphEdge.source_node_id,
                GraphEdge.target_node_id,
                GraphEdge.relationship_type,
                GraphEdge.snapshot_id,
            ).where(GraphEdge.snapshot_id == snapshot_id)
        ).all()
    )

    # ──── Step 3: Plan SCHEMA nodes ────
    # Schemas have to materialise first because table nodes will emit
    # DEPENDS_ON edges pointing at them. We collect the rows we need to
    # insert into a list of dicts and flush via `bulk_insert_mappings`
    # below — far cheaper than per-row `session.add` + `flush`.
    schema_node_inserts: List[dict] = []
    schema_uid_by_name: Dict[str, str] = {}
    schema_keys_to_create: List[Tuple[str, str, int]] = []

    for schema in schema_rows:
        object_type = "SCHEMA"
        object_name = schema.schema_name
        key = (object_type, object_name, snapshot_id)
        if key in existing_nodes_by_key:
            schema_uid_by_name[object_name] = existing_node_uids[existing_nodes_by_key[key]]
            continue
        uid = f"{object_type}:{object_name}:{snapshot_id}"
        schema_node_inserts.append({
            "object_type": object_type,
            "object_name": object_name,
            "snapshot_id": snapshot_id,
            "node_metadata": None,
            "schema_name": object_name,
            "node_uid": uid,
        })
        schema_uid_by_name[object_name] = uid
        schema_keys_to_create.append(key)

    # ──── Step 4: Plan TABLE / VIEW nodes ────
    # Build a parallel index `all_table_names` (lower-cased) so Step 7
    # can resolve `_id` columns into target tables in O(1).
    # Value is a list so multi-schema warehouses (e.g. SALES_EU.CUSTOMERS and
    # SALES_US.CUSTOMERS) don't silently overwrite each other — we only emit a
    # FEEDS edge when exactly one table with that name exists (unambiguous).
    table_node_inserts: List[dict] = []
    table_uid_by_qname: Dict[Tuple[str, str], str] = {}
    table_keys_to_create: List[Tuple[str, str, int, Tuple[str, str]]] = []
    all_table_names: Dict[str, List[Tuple[str, str]]] = {}

    for schema_name, table in table_rows:
        object_type = table.object_type
        object_name = f"{schema_name}.{table.table_name}"
        key = (object_type, object_name, snapshot_id)
        all_table_names.setdefault(table.table_name.lower(), []).append(
            (schema_name, table.table_name)
        )

        if key in existing_nodes_by_key:
            table_uid_by_qname[(schema_name, table.table_name)] = existing_node_uids[existing_nodes_by_key[key]]
            continue

        uid = f"{object_type}:{object_name}:{snapshot_id}"
        table_node_inserts.append({
            "object_type": object_type,
            "object_name": object_name,
            "snapshot_id": snapshot_id,
            "node_metadata": None,
            "schema_name": schema_name,
            "node_uid": uid,
        })
        table_uid_by_qname[(schema_name, table.table_name)] = uid
        table_keys_to_create.append((object_type, object_name, snapshot_id, (schema_name, table.table_name)))

    # ──── Step 5: Bulk-insert nodes, then re-query to recover IDs ────
    # `bulk_insert_mappings` doesn't return generated PKs (SQLAlchemy
    # 2.0 docs are clear on this), so after the insert we run a single
    # SELECT to map back from `(object_type, object_name)` → `node_id`.
    # That's two queries to insert 240k rows instead of 240k flushes.
    if schema_node_inserts:
        for i in range(0, len(schema_node_inserts), _BULK_INSERT_BATCH_SIZE):
            session.bulk_insert_mappings(
                GraphNode, schema_node_inserts[i:i + _BULK_INSERT_BATCH_SIZE]
            )
    if table_node_inserts:
        for i in range(0, len(table_node_inserts), _BULK_INSERT_BATCH_SIZE):
            session.bulk_insert_mappings(
                GraphNode, table_node_inserts[i:i + _BULK_INSERT_BATCH_SIZE]
            )

    # Re-fetch every node for this snapshot so we have the final
    # natural-key → node_id mapping. Cheaper than tracking inserts
    # individually because we need the same map for downstream FEEDS
    # edge creation anyway.
    node_id_by_key: Dict[Tuple[str, str, int], int] = dict(existing_nodes_by_key)
    if schema_node_inserts or table_node_inserts:
        for node_id, otype, oname, sid in session.execute(
            select(
                GraphNode.node_id,
                GraphNode.object_type,
                GraphNode.object_name,
                GraphNode.snapshot_id,
            ).where(GraphNode.snapshot_id == snapshot_id)
        ).all():
            node_id_by_key[(otype, oname, sid)] = node_id

    schema_node_ids: Dict[str, int] = {
        s.schema_name: node_id_by_key[("SCHEMA", s.schema_name, snapshot_id)]
        for s in schema_rows
        if ("SCHEMA", s.schema_name, snapshot_id) in node_id_by_key
    }
    table_node_ids: Dict[Tuple[str, str], int] = {}
    for schema_name, table in table_rows:
        key = (table.object_type, f"{schema_name}.{table.table_name}", snapshot_id)
        if key in node_id_by_key:
            table_node_ids[(schema_name, table.table_name)] = node_id_by_key[key]

    # ──── Step 6: Plan DEPENDS_ON + FEEDS edges ────
    # Same in-memory dedup pattern as nodes: collect dicts, bulk-insert
    # at the end. The set `planned_edges` doubles as a within-this-call
    # dedup so we don't insert the same edge twice from the same run
    # (e.g. a table that has both `customer_id` and `customers_id`
    # columns — first match wins via the `break` below, but the dedup
    # is the safety net).
    edge_inserts: List[dict] = []
    planned_edges: Set[Tuple[int, int, str, int]] = set(existing_edges)

    def _plan_edge(
        source_node_id: int,
        target_node_id: int,
        relationship_type: str,
        source_uid: str,
        target_uid: str,
    ) -> None:
        key = (source_node_id, target_node_id, relationship_type, snapshot_id)
        if key in planned_edges:
            return
        planned_edges.add(key)
        edge_inserts.append({
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relationship_type": relationship_type,
            "snapshot_id": snapshot_id,
            "from_node_uid": source_uid,
            "to_node_uid": target_uid,
            "edge_type": relationship_type,
        })

    # DEPENDS_ON edges: each table → its schema.
    for schema_name, table in table_rows:
        tbl_node_id = table_node_ids.get((schema_name, table.table_name))
        sch_node_id = schema_node_ids.get(schema_name)
        if tbl_node_id is None or sch_node_id is None:
            continue
        _plan_edge(
            source_node_id=tbl_node_id,
            target_node_id=sch_node_id,
            relationship_type="DEPENDS_ON",
            source_uid=table_uid_by_qname.get((schema_name, table.table_name), ""),
            target_uid=schema_uid_by_name.get(schema_name, ""),
        )

    # ──── Step 7: FEEDS edges (FK heuristic on `_id` column names) ────
    # SCION typically doesn't have access to declared foreign keys (data
    # warehouses rarely enforce them), so we approximate lineage by
    # column-name convention: a column `customer_id` on table ACCOUNTS
    # implies CUSTOMERS feeds ACCOUNTS. v1.10 fixed the direction —
    # FEEDS edges are always source→target in the direction of data
    # flow, so `customers FEEDS accounts`, NOT the other way round.
    for schema_name, table_name, column_name in column_rows:
        col_lower = column_name.lower()
        if not col_lower.endswith("_id"):
            continue

        prefix = col_lower[:-3]
        candidates = (prefix, prefix + "s", prefix + "es")

        fk_holder_node_id = table_node_ids.get((schema_name, table_name))
        if fk_holder_node_id is None:
            continue
        fk_holder_uid = table_uid_by_qname.get((schema_name, table_name), "")

        for candidate in candidates:
            matches = all_table_names.get(candidate)
            if not matches:
                continue
            # Only emit an edge when the name is unambiguous across schemas.
            # Two schemas both having CUSTOMERS would create a wrong cross-schema
            # FEEDS edge, so we skip the heuristic in that case.
            if len(matches) != 1:
                continue
            ref = matches[0]
            ref_node_id = table_node_ids.get(ref)
            if ref_node_id is None or ref_node_id == fk_holder_node_id:
                # Skip self-referencing tables — a table whose own
                # primary key happens to satisfy the heuristic shouldn't
                # spawn a self-edge.
                continue
            _plan_edge(
                source_node_id=ref_node_id,
                target_node_id=fk_holder_node_id,
                relationship_type="FEEDS",
                source_uid=table_uid_by_qname.get(ref, ""),
                target_uid=fk_holder_uid,
            )
            # First candidate wins. If both `customer` and `customers`
            # exist, take the singular and stop — otherwise we'd
            # double-count the same semantic link.
            break

    # ──── Step 8: Bulk-insert edges ────
    # Existing edges were already in `planned_edges` so they were never
    # appended to `edge_inserts`. Anything left here is genuinely new.
    if edge_inserts:
        for i in range(0, len(edge_inserts), _BULK_INSERT_BATCH_SIZE):
            session.bulk_insert_mappings(
                GraphEdge, edge_inserts[i:i + _BULK_INSERT_BATCH_SIZE]
            )
