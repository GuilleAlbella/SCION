"""Repository layer for persisting snapshot metadata using SQLAlchemy ORM.

This module encapsulates all ORM interactions related to snapshot persistence,
so that higher layers do not need to manage sessions or transactions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Dict, Iterable, List, Tuple

from sqlalchemy import inspect
from sqlalchemy.orm import Session, sessionmaker

from app.db.engine import engine as db_engine
from app.db.models.column_snapshot import ColumnSnapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.snapshot import Snapshot
from app.db.models.table_snapshot import TableSnapshot
from app.graph.graph_models import GraphEdge, GraphNode
from app.snapshot.normalizer import NormalizedSchema


@dataclass
class SnapshotRepository:
    """Persist snapshot metadata and manage ORM session lifecycle.

    The repository is responsible for creating the snapshot and all associated
    schema, table, and column records within a single transaction, ensuring
    that either the entire snapshot is stored or none of it is.
    """

    session_factory: sessionmaker

    def persist_snapshot(
        self,
        *,
        source_system: str,
        description: str | None,
        is_baseline: bool,
        schemas: Iterable[NormalizedSchema],
    ) -> int:
        """Persist a single snapshot and its associated metadata.

        A new session and transaction are created for the snapshot. On success
        the transaction is committed and the new snapshot_id is returned; on
        failure the transaction is rolled back and the exception is re-raised.
        """

        session: Session = self.session_factory()
        try:
            snapshot = Snapshot(
                snapshot_time=datetime.now(UTC),
                source_system=source_system,
                description=description,
                is_baseline=is_baseline,
            )
            session.add(snapshot)
            session.flush()  # Ensure snapshot_id is populated before children.

            # Precompute inspector for foreign key discovery.
            inspector = inspect(db_engine)

            # Collect pending FK relationships as logical table pairs so that
            # edges can be created after all GraphNodes exist.
            pending_fks: List[Tuple[str, str, str, str]] = []

            # Map from (schema_name, table_name) to the corresponding
            # GraphNode so that we can resolve node_ids and node_uids when
            # creating edges.
            nodes_by_table: Dict[Tuple[str, str], GraphNode] = {}

            for schema in schemas:
                schema_row = SchemaSnapshot(
                    snapshot_id=snapshot.snapshot_id,
                    schema_name=schema.schema_name,
                )
                session.add(schema_row)
                session.flush()  # Obtain schema_id for related tables.

                for table in schema.tables:
                    table_row = TableSnapshot(
                        schema_id=schema_row.schema_id,
                        table_name=table.table_name,
                        object_type=table.object_type,
                    )
                    session.add(table_row)
                    session.flush()  # Obtain table_id for related columns.

                    # For each persisted table, create a corresponding
                    # GraphNode in the system graph for this snapshot.
                    node_uid = f"table:{schema.schema_name}.{table.table_name}"
                    graph_node = GraphNode(
                        snapshot_id=snapshot.snapshot_id,
                        node_uid=node_uid,
                        object_type="TABLE",
                        object_name=table.table_name,
                        schema_name=schema.schema_name,
                        node_metadata=None,
                    )
                    session.add(graph_node)
                    session.flush()  # Ensure node_id is populated.

                    nodes_by_table[(schema.schema_name, table.table_name)] = graph_node

                    # Discover real foreign key relationships for this table
                    # using the SQLAlchemy inspector, without heuristics.
                    fk_rows = inspector.get_foreign_keys(
                        table.table_name,
                        schema=schema.schema_name or None,
                    )
                    for fk in fk_rows:
                        ref_schema = fk.get("referred_schema") or schema.schema_name
                        ref_table = fk.get("referred_table")
                        if not ref_table:
                            continue
                        pending_fks.append(
                            (
                                schema.schema_name,
                                table.table_name,
                                str(ref_schema),
                                str(ref_table),
                            )
                        )

                    for column in table.columns:
                        column_row = ColumnSnapshot(
                            table_id=table_row.table_id,
                            column_name=column.column_name,
                            data_type=column.data_type,
                            nullable=column.nullable,
                            ordinal_position=column.ordinal_position,
                        )
                        session.add(column_row)

            # After all nodes have been created for this snapshot, persist
            # edges representing explicit foreign key relationships. This is
            # done in the same transaction so that the graph remains
            # consistent with the snapshot state.
            for schema_name, table_name, ref_schema, ref_table in pending_fks:
                source_node = nodes_by_table.get((schema_name, table_name))
                target_node = nodes_by_table.get((ref_schema, ref_table))
                if source_node is None or target_node is None:
                    # If either side is missing, we skip the edge; we do not
                    # invent nodes or infer relationships.
                    continue

                edge = GraphEdge(
                    snapshot_id=snapshot.snapshot_id,
                    source_node_id=source_node.node_id,
                    target_node_id=target_node.node_id,
                    relationship_type="FK",
                    from_node_uid=source_node.node_uid,
                    to_node_uid=target_node.node_uid,
                    edge_type="FOREIGN_KEY",
                    edge_metadata=None,
                )
                session.add(edge)

            session.commit()
            return snapshot.snapshot_id
        except Exception:
            # A failure anywhere in the snapshot persistence should roll back
            # the entire transaction to avoid storing partial snapshots.
            session.rollback()
            raise
        finally:
            session.close()
