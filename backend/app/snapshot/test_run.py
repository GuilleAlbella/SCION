"""Minimal manual entry point for snapshot ingestion.

This script is intended for ad-hoc, local verification of the snapshot
ingestion pipeline. It wires together the SQLAlchemy engine, metadata runner,
normalization, and repository via the SnapshotOrchestrator, then prints a
summary of what was ingested. It is not part of the automated test suite.
"""

from __future__ import annotations

from typing import List

import os
import sys

from sqlalchemy import create_engine

# When this module is executed directly (e.g. ``python backend/app/snapshot/test_run.py``),
# the repository root is not automatically added to sys.path, so the top-level ``app``
# package would not be importable. The repository root is one level above the "backend"
# directory; we compute it relative to this file to keep the script relocatable.
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir)
)
BACKEND_PATH = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_PATH not in sys.path:
    sys.path.insert(0, BACKEND_PATH)

from app.metadata.runner.engine import SqlAlchemyExecutionEngine
from app.metadata.runner.runner import MetadataRunner
from app.metadata.templates.column import ColumnTemplate
from app.metadata.templates.schema import SchemaTemplate
from app.metadata.templates.table import TableTemplate
from app.snapshot.orchestrator import SnapshotOrchestrator


def main() -> None:
    """Run a single snapshot ingestion against the local SQLite demo DB.

    This function uses the same metadata templates and runner infrastructure
    as the rest of the application, but executes a single end-to-end flow in
    a simple, synchronous manner for manual inspection.
    """

    # Create a SQLAlchemy Engine pointing at the existing demo SQLite
    # database file. The path is built from PROJECT_ROOT so it matches the
    # same kalido_lite.db file that Alembic uses via alembic.ini.
    db_path = os.path.join(PROJECT_ROOT, "kalido_lite.db")
    engine = create_engine(f"sqlite:///{db_path}")

    # Instantiate the metadata runner explicitly for SQLite so that we can
    # verify the adapter rendering and result shapes before persisting.
    execution_engine = SqlAlchemyExecutionEngine(engine)
    runner = MetadataRunner("sqlite", execution_engine)

    # Execute metadata extraction for schemas, tables, and columns. The
    # results will be used both for basic counting and for the orchestrated
    # snapshot ingestion that follows.
    schema_rows: List[dict] = runner.run_schema(SchemaTemplate())
    table_rows: List[dict] = runner.run_table(TableTemplate())
    column_rows: List[dict] = runner.run_column(ColumnTemplate())

    # Create the snapshot orchestrator, which will internally use the same
    # engine and engine name to drive extraction, normalization, and
    # persistence. For this minimal test, we use simple, hard-coded metadata
    # about the snapshot itself.
    orchestrator = SnapshotOrchestrator(engine=engine, engine_name="sqlite")
    snapshot_id = orchestrator.create_snapshot(
        source_system="demo",  # Indicates this snapshot was created for a manual demo run.
        description="Manual test_run snapshot",
        is_baseline=False,
    )

    # Print a concise summary to stdout so the operator can confirm that the
    # ingestion completed and inspect the approximate scale of the metadata
    # captured in this run.
    print(f"snapshot_id: {snapshot_id}")
    print(f"schemas: {len(schema_rows)}")
    print(f"tables: {len(table_rows)}")
    print(f"columns: {len(column_rows)}")


if __name__ == "__main__":
    main()
