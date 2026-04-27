"""High-level engine for orchestrating metadata snapshot creation.

This module defines the `SnapshotEngine`, which coordinates the lifecycle of
creating a snapshot:

- Delegates metadata loading to a `SnapshotLoader` instance.
- Persists the resulting structures using the existing SQLAlchemy ORM models.
- Ensures that all changes happen within a single transaction.

It does not execute templates directly and does not implement diff or
business-analysis logic; its sole responsibility is to take already-loaded
metadata and persist it as a coherent snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Dict, Tuple

from sqlalchemy.orm import Session, sessionmaker

from app.db.engine import engine
from app.db.models.column_snapshot import ColumnSnapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.snapshot import Snapshot
from app.db.models.table_snapshot import TableSnapshot
from app.graph.graph_models import GraphNode
from app.snapshot.snapshot_loader import SnapshotLoader
from app.snapshot.template_sets import DEFAULT_SNAPSHOT_TEMPLATE_SET
from app.snapshot.validator import validate_snapshot


class InvalidSnapshotExecution(RuntimeError):
    """Domain-level error raised when a snapshot execution is invalid.

    This is used to signal that the loader returned metadata that does not
    meet the minimal validity constraints required by the engine. Any
    occurrence of this exception must result in a full transaction rollback
    and no snapshot-related rows left in the database.
    """


@dataclass
class SnapshotEngine:
    """Orchestrate the creation of metadata snapshots.

    The engine relies on a `SnapshotLoader` to retrieve normalized raw
    metadata and uses SQLAlchemy ORM models to persist this metadata in a
    single transaction.
    """

    loader: SnapshotLoader
    template_set: Tuple[str, ...] = DEFAULT_SNAPSHOT_TEMPLATE_SET

    def __post_init__(self) -> None:
        """Initialize the session factory bound to the shared application engine.

        A dedicated session factory keeps transaction management localized to
        this engine while still reusing the globally configured `engine`.
        """

        self._session_factory: sessionmaker[Session] = sessionmaker(bind=engine)

    def create_snapshot(
        self,
        source_system: str,
        description: str,
        is_baseline: bool = False,
    ) -> int:
        """Create a new metadata snapshot and return its snapshot_id.

        The flow is:

        1. Open a SQLAlchemy session and begin a transaction.
        2. Insert a `Snapshot` row and flush to obtain `snapshot_id`.
        3. Delegate to the loader to obtain in-memory metadata structures.
        4. Persist schemas, tables, and columns, maintaining in-memory maps
           for foreign key resolution.
        5. Commit the transaction and return the new `snapshot_id`.
        6. On any error, roll back and re-raise the exception.
        """

        session: Session = self._session_factory()
        try:
            # Step 2 – create the snapshot record and flush to get snapshot_id.
            snapshot = Snapshot(
                snapshot_time=datetime.now(UTC),
                source_system=source_system,
                description=description,
                is_baseline=is_baseline,
            )
            session.add(snapshot)
            session.flush()  # populate snapshot.snapshot_id

            # Step 3 – load normalized raw metadata from the loader.
            data = self.loader.load()
            schemas_meta = data["schemas"]
            tables_meta = data["tables"]
            columns_meta = data["columns"]

            # Step 4 – persist schemas and build a map from schema_name to schema_id.
            schema_id_by_name: Dict[str, int] = {}
            for schema_meta in schemas_meta:
                schema_row = SchemaSnapshot(
                    snapshot_id=snapshot.snapshot_id,
                    schema_name=schema_meta.schema_name,
                )
                session.add(schema_row)
                session.flush()
                schema_id_by_name[schema_meta.schema_name] = schema_row.schema_id

            # Step 5 – persist tables and build a map from (schema_name, table_name)
            # to table_id. In parallel, create GraphNode entries for each table so
            # that the structural graph for this snapshot is fully populated.
            table_id_by_key: Dict[Tuple[str, str], int] = {}
            for table_meta in tables_meta:
                schema_id = schema_id_by_name[table_meta.schema_name]
                table_row = TableSnapshot(
                    schema_id=schema_id,
                    table_name=table_meta.table_name,
                    object_type=table_meta.object_type,
                )
                session.add(table_row)
                session.flush()
                table_id_by_key[(table_meta.schema_name, table_meta.table_name)] = (
                    table_row.table_id
                )

                # Create a graph node for this table within the current snapshot.
                node_uid = f"table:{table_meta.schema_name}.{table_meta.table_name}"
                print(
                    "[SnapshotEngine] Creating GraphNode",
                    snapshot_id=snapshot.snapshot_id,
                    schema_name=table_meta.schema_name,
                    table_name=table_meta.table_name,
                )
                node = GraphNode(
                    snapshot_id=snapshot.snapshot_id,
                    node_uid=node_uid,
                    object_type="TABLE",
                    object_name=table_meta.table_name,
                    schema_name=table_meta.schema_name,
                    node_metadata=None,
                )
                session.add(node)

            # Step 6 – persist columns by resolving table_id from the map.
            for column_meta in columns_meta:
                table_id = table_id_by_key[
                    (column_meta.schema_name, column_meta.table_name)
                ]
                column_row = ColumnSnapshot(
                    table_id=table_id,
                    column_name=column_meta.column_name,
                    data_type=column_meta.data_type,
                    nullable=column_meta.nullable,
                    ordinal_position=column_meta.ordinal_position,
                )
                session.add(column_row)

            # Step 7 – validate structural integrity for this snapshot.
            validate_snapshot(
                session=session,
                snapshot=snapshot,
                template_set=self.template_set,
                error_cls=InvalidSnapshotExecution,
            )

            # Step 8 – commit the transaction and return the snapshot_id.
            session.commit()
            return snapshot.snapshot_id
        except Exception:
            # Step 8 – ensure that partial snapshots are not persisted.
            session.rollback()
            raise
        finally:
            session.close()
