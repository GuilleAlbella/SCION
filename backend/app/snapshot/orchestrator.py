"""High-level orchestration for snapshot ingestion.

This module coordinates metadata extraction via the runner, normalization into
canonical structures, and persistence using the repository layer. It focuses
on a single-snapshot ingestion workflow without diff or lineage logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.metadata.runner.engine import SqlAlchemyExecutionEngine
from app.metadata.runner.runner import MetadataRunner
from app.metadata.templates.schema import SchemaTemplate
from app.metadata.templates.table import TableTemplate
from app.metadata.templates.column import ColumnTemplate
from app.snapshot.normalizer import SnapshotNormalizer
from app.snapshot.repository import SnapshotRepository


@dataclass
class SnapshotOrchestrator:
    """Coordinate extraction, normalization, and persistence of a snapshot.

    The orchestrator wires together the metadata runner, normalizer, and
    repository. It assumes a single snapshot per execution and delegates
    engine-specific concerns to the metadata layer.
    """

    engine: Engine
    engine_name: str

    def __post_init__(self) -> None:
        """Initialize helper components needed for snapshot ingestion.

        The SQLAlchemy Engine is wrapped in a read-only execution engine and
        combined with the logical metadata runner. A dedicated normalizer and
        repository are also created for this orchestrator instance.
        """

        self._session_factory = sessionmaker(bind=self.engine)
        self._execution_engine = SqlAlchemyExecutionEngine(self.engine)
        self._runner = MetadataRunner(self.engine_name, self._execution_engine)
        self._normalizer = SnapshotNormalizer()
        self._repository = SnapshotRepository(session_factory=self._session_factory)

    def create_snapshot(
        self,
        *,
        source_system: str,
        description: Optional[str] = None,
        is_baseline: bool = False,
    ) -> int:
        """Run the full snapshot ingestion workflow and return snapshot_id.

        The workflow is:
        1. Extract raw schema, table, and column metadata via the runner.
        2. Normalize the raw rows into canonical structures.
        3. Persist the snapshot and its metadata via the repository.
        """

        # ──── Step 1: Extract raw metadata from the source system ────
        # Templates are engine-agnostic: the runner rewrites them into the
        # appropriate dialect (Teradata vs Postgres vs SQLite). This is the
        # only place we touch the source DB in the whole ingestion flow.
        schema_rows = self._runner.run_schema(SchemaTemplate())
        table_rows = self._runner.run_table(TableTemplate())
        column_rows = self._runner.run_column(ColumnTemplate())

        # ──── Step 2: Normalize into canonical in-memory structures ────
        # Normalization is where engine-specific quirks (case, data-type
        # aliases, nullable encoding) get smoothed out so the diff engine
        # and repository see a uniform shape regardless of source.
        normalized_schemas = self._normalizer.normalize(
            schema_rows=schema_rows,
            table_rows=table_rows,
            column_rows=column_rows,
        )

        # ──── Step 3: Persist snapshot + metadata in a single transaction ────
        # The repository handles the whole write as one unit so a partial
        # snapshot can never appear in the DB (critical for diff integrity).
        snapshot_id = self._repository.persist_snapshot(
            source_system=source_system,
            description=description,
            is_baseline=is_baseline,
            schemas=normalized_schemas,
        )

        return snapshot_id
