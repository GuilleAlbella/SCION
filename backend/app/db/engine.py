"""Application-level SQLAlchemy Engine configuration.

This module defines a single, canonical SQLAlchemy Engine instance for the
application runtime. It is intentionally separate from Alembic's configuration
so that application code does not depend on migration tooling, and Alembic
can manage its own connection settings independently.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine

# Compute the project root from this file location so that the default SQLite
# database path is deterministic and does not depend on the current working
# directory. Relative SQLite URLs can otherwise create different files when
# commands are run from different folders.
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir)
)
DEFAULT_SQLITE_PATH = os.path.join(PROJECT_ROOT, "kalido_lite.db")
DEFAULT_SQLITE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH}"

# DATABASE_URL allows the runtime database to be configured without changing
# code. When not provided, a SQLite file in the project root is used as a
# safe default so that the application can run without an external database.
DATABASE_URL: str = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)

# The Engine is created at import time so that downstream components (such as
# repositories, orchestrators, or web frameworks) can rely on a single,
# shared Engine instance without each having to manage engine lifecycles.
engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)
