from __future__ import annotations

from typing import Dict, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot
from app.graph.graph_models import GraphEdge, GraphNode


def build_graph_for_snapshot(snapshot_id: int) -> None:
    """Build technical lineage graph for a given snapshot.

    Idempotent: repeated executions for the same snapshot do not create
    duplicate nodes or edges.

    Creates:
    - SCHEMA nodes
    - TABLE/VIEW nodes with DEPENDS_ON edges to their schema
    - FEEDS edges between tables based on FK-like column naming conventions
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


def _build_graph_for_snapshot_in_session(session: Session, snapshot_id: int) -> None:
    """Internal helper that performs the actual graph construction."""

    # ──── Step 1: Load snapshot metadata ────
    # We pull schemas / tables / columns in three separate queries (rather
    # than one big join) to keep row shapes simple and because tables/columns
    # require joining back to SchemaSnapshot to recover the schema name.
    # Load schemas, tables and columns for the snapshot.
    schema_rows = session.scalars(
        select(SchemaSnapshot).where(SchemaSnapshot.snapshot_id == snapshot_id)
    ).all()

    table_rows = (
        session.execute(
            select(SchemaSnapshot.schema_name, TableSnapshot)
            .join(TableSnapshot, TableSnapshot.schema_id == SchemaSnapshot.schema_id)
            .where(SchemaSnapshot.snapshot_id == snapshot_id)
        ).all()
    )

    column_rows = (
        session.execute(
            select(
                SchemaSnapshot.schema_name,
                TableSnapshot.table_name,
                ColumnSnapshot.column_name,
            )
            .join(TableSnapshot, TableSnapshot.schema_id == SchemaSnapshot.schema_id)
            .join(ColumnSnapshot, ColumnSnapshot.table_id == TableSnapshot.table_id)
            .where(SchemaSnapshot.snapshot_id == snapshot_id)
        ).all()
    )

    # ──── Step 2: Seed idempotency indexes from existing rows ────
    # Pre-loading existing nodes lets us skip duplicate inserts on re-runs
    # without relying on a DB unique constraint failure (which would abort
    # the whole transaction). The natural key is (type, name, snapshot_id).
    # Idempotent node creation: track existing nodes by natural key.
    existing_nodes: Dict[Tuple[str, str, int], int] = {}
    existing_node_uids: Dict[int, str] = {}

    for node in session.query(GraphNode).filter(GraphNode.snapshot_id == snapshot_id):
        key = (node.object_type, node.object_name, node.snapshot_id)
        existing_nodes[key] = node.node_id
        existing_node_uids[node.node_id] = node.node_uid or ""

    # ──── Step 3: Create SCHEMA nodes ────
    # Schemas must be created first because table nodes will emit
    # DEPENDS_ON edges pointing at them. We cache their node_ids by name.
    # -- Schema nodes --
    schema_node_ids: Dict[str, int] = {}

    for schema in schema_rows:
        object_type = "SCHEMA"
        object_name = schema.schema_name
        key = (object_type, object_name, snapshot_id)

        node_id = existing_nodes.get(key)
        if node_id is None:
            uid = f"{object_type}:{object_name}:{snapshot_id}"
            node = GraphNode(
                object_type=object_type,
                object_name=object_name,
                snapshot_id=snapshot_id,
                node_metadata=None,
                schema_name=object_name,
                node_uid=uid,
            )
            session.add(node)
            session.flush()
            node_id = node.node_id
            existing_nodes[key] = node_id
            existing_node_uids[node_id] = uid

        schema_node_ids[schema.schema_name] = node_id

    # ──── Step 4: Create TABLE/VIEW nodes + DEPENDS_ON edges ────
    # While we walk tables we also build a case-insensitive name index
    # (all_table_names) which Step 5 uses to resolve FK-like columns
    # into target tables.
    # -- Table/View nodes + DEPENDS_ON edges to schema --
    table_node_ids: Dict[Tuple[str, str], int] = {}
    # Build a set of all table names (lower) for FK matching
    all_table_names: Dict[str, Tuple[str, str]] = {}  # lower_name -> (schema, table)

    for schema_name, table in table_rows:
        object_type = table.object_type
        object_name = f"{schema_name}.{table.table_name}"
        key = (object_type, object_name, snapshot_id)

        node_id = existing_nodes.get(key)
        if node_id is None:
            uid = f"{object_type}:{object_name}:{snapshot_id}"
            node = GraphNode(
                object_type=object_type,
                object_name=object_name,
                snapshot_id=snapshot_id,
                node_metadata=None,
                schema_name=schema_name,
                node_uid=uid,
            )
            session.add(node)
            session.flush()
            node_id = node.node_id
            existing_nodes[key] = node_id
            existing_node_uids[node_id] = uid

        table_node_ids[(schema_name, table.table_name)] = node_id
        all_table_names[table.table_name.lower()] = (schema_name, table.table_name)

        # DEPENDS_ON edge: table -> schema
        schema_node_id = schema_node_ids.get(schema_name)
        if schema_node_id is not None:
            _ensure_edge(
                session=session,
                snapshot_id=snapshot_id,
                source_node_id=node_id,
                target_node_id=schema_node_id,
                relationship_type="DEPENDS_ON",
                source_uid=existing_node_uids.get(node_id, ""),
                target_uid=existing_node_uids.get(schema_node_id, ""),
            )

    # ──── Step 5: Infer FEEDS edges from FK-naming conventions ────
    # SCION does not have access to real foreign-key metadata in many source
    # systems (especially data warehouses where FKs are rarely enforced),
    # so we approximate lineage via a naming-convention heuristic:
    # a column "customer_id" on table ACCOUNTS implies that the CUSTOMERS
    # table is upstream of ACCOUNTS (customers data flows INTO accounts).
    # Direction semantics (v1.10 fix): FEEDS edges are always source→target
    # in the direction of data flow, so `customers FEEDS accounts`, NOT
    # the other way round. Prior to v1.10 this heuristic emitted the edge
    # inverted, which made every fact-to-dimension reference show as
    # "dimension depends on fact" in Lineage — semantically backwards for
    # every data-warehouse demo we ran.
    # -- FEEDS edges: detect FK-like columns (_id suffix) --
    for schema_name, table_name, column_name in column_rows:
        col_lower = column_name.lower()
        if not col_lower.endswith("_id"):
            continue

        # Strip the "_id" suffix to get the candidate entity name,
        # then try singular, -s plural, and -es plural forms.
        prefix = col_lower[:-3]  # remove "_id"
        candidates = [prefix, prefix + "s", prefix + "es"]

        # The table that HOLDS the FK column (e.g. `accounts` with
        # `customer_id`). In FEEDS semantics this is the *downstream*
        # consumer — data from the referenced entity flows INTO it.
        fk_holder_key = (schema_name, table_name)
        fk_holder_node_id = table_node_ids.get(fk_holder_key)
        if fk_holder_node_id is None:
            continue

        for candidate in candidates:
            if candidate in all_table_names:
                ref_schema, ref_table = all_table_names[candidate]
                ref_key = (ref_schema, ref_table)
                # The referenced entity (e.g. `customers`). In FEEDS
                # semantics this is the *upstream* producer — its data
                # flows into the FK-holder table.
                ref_node_id = table_node_ids.get(ref_key)

                # Skip self-loops: a table with its own id column pointing
                # to itself shouldn't create an edge.
                if ref_node_id is None or ref_node_id == fk_holder_node_id:
                    continue

                # Edge direction: referenced_entity → fk_holder (upstream→downstream)
                _ensure_edge(
                    session=session,
                    snapshot_id=snapshot_id,
                    source_node_id=ref_node_id,
                    target_node_id=fk_holder_node_id,
                    relationship_type="FEEDS",
                    source_uid=existing_node_uids.get(ref_node_id, ""),
                    target_uid=existing_node_uids.get(fk_holder_node_id, ""),
                )
                # First candidate match wins: if both "customer" and
                # "customers" exist, we take the singular form and stop
                # — otherwise we'd double-count the same semantic link.
                break  # Only create one edge per FK column


def _ensure_edge(
    *,
    session: Session,
    snapshot_id: int,
    source_node_id: int,
    target_node_id: int,
    relationship_type: str,
    source_uid: str = "",
    target_uid: str = "",
) -> None:
    """Idempotently create a GraphEdge if it does not exist."""

    exists = (
        session.query(GraphEdge)
        .filter(
            GraphEdge.source_node_id == source_node_id,
            GraphEdge.target_node_id == target_node_id,
            GraphEdge.relationship_type == relationship_type,
            GraphEdge.snapshot_id == snapshot_id,
        )
        .first()
    )

    if exists is not None:
        return

    session.add(
        GraphEdge(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relationship_type=relationship_type,
            snapshot_id=snapshot_id,
            from_node_uid=source_uid,
            to_node_uid=target_uid,
            edge_type=relationship_type,
        )
    )
