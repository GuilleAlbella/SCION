"""Bootstrap utility for recreating the local SQLite demo database.

This script is intended for local/demo usage only. It:
- Resolves the project root deterministically based on this file location.
- Recreates the SQLite database file at the project root.
- Imports the SQLAlchemy Base (which registers ORM models via side effects).
- Uses Base.metadata.create_all(bind=engine) to create tables.
- Verifies that the expected tables exist using SQLAlchemy inspection.

It does not rely on Alembic, and it is separate from migration tooling so that
schema bootstrapping for demos is explicit and reproducible.
"""

from __future__ import annotations

import os
import sys
from typing import Set

from sqlalchemy import inspect


def _resolve_project_root() -> str:
    """Return the absolute path to the project root directory.

    The project root is computed relative to this file so that the script
    behaves consistently regardless of the current working directory.
    """

    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))


def _main() -> int:
    """Recreate the SQLite demo database and verify its schema.

    The function returns an exit code so that callers can detect failure in
    automated contexts, even though this script is primarily for manual use.
    """

    project_root = _resolve_project_root()
    db_path = os.path.join(project_root, "kalido_lite.db")

    print(f"[bootstrap] Project root: {project_root}")
    print(f"[bootstrap] SQLite database path: {db_path}")

    # Ensure that the top-level "app" package is importable when this script
    # is executed directly. This avoids depending on the current working
    # directory for package resolution and mirrors the runtime import layout.
    backend_path = os.path.join(project_root, "backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    # Remove the existing database file to ensure we start from a clean state.
    # This avoids stale schemas or mismatched migrations during local testing.
    if os.path.exists(db_path):
        print("[bootstrap] Removing existing database file...")
        os.remove(db_path)

    # Import Base to ensure all ORM models are registered in Base.metadata via
    # the side-effect imports defined in app.db.base. This is critical so that
    # create_all() has visibility into all tables that should be created.
    from app.db.base import Base  # noqa: F401
    from app.db.engine import engine

    print("[bootstrap] Creating tables using Base.metadata.create_all()...")
    Base.metadata.create_all(bind=engine)

    # Use SQLAlchemy's inspection utilities to query the set of tables that
    # actually exist in the database after create_all() has run.
    inspector = inspect(engine)
    tables: Set[str] = set(inspector.get_table_names())

    print(f"[bootstrap] Tables found: {sorted(tables)}")

    expected_tables: Set[str] = {
        "snapshot",
        "schema_snapshot",
        "table_snapshot",
        "column_snapshot",
    }

    missing = expected_tables - tables
    if missing:
        print("[bootstrap] FAILURE: Missing expected tables:")
        for name in sorted(missing):
            print(f"  - {name}")
        return 1

    print("[bootstrap] SUCCESS: Database bootstrapped correctly and all expected tables exist.")
    return 0


if __name__ == "__main__":
    # Exit code is propagated so that callers can detect failure when running
    # this script from automation or command-line environments.
    sys.exit(_main())
