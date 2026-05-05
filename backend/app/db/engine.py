"""Application-level SQLAlchemy Engine configuration.

This module defines a single, canonical SQLAlchemy Engine instance for the
application runtime. It is intentionally separate from Alembic's configuration
so that application code does not depend on migration tooling, and Alembic
can manage its own connection settings independently.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine, event, text


_logger = logging.getLogger(__name__)

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


# ──── SQLite-specific tuning ────
# Enable Write-Ahead Logging (WAL) on every new SQLite connection.
#
# Why this matters: SQLite's default `journal_mode = DELETE` uses a
# rollback journal and serialises readers with the active writer. Our
# workload deliberately mixes reads (the `/dict-import/{id}/progress`
# poll fires every second during a 5-minute import, plus `/snapshots`
# refreshes from open browser tabs) with one big writer (the persist
# transaction). Under DELETE, every reader stalls the writer for the
# duration of the read; we measured a 3× regression in persist wall
# time (~4 min → ~12 min) versus running the same writer with no
# concurrent readers.
#
# In WAL mode, writers append to a separate `*.db-wal` file and
# readers see a consistent snapshot of the main DB. They no longer
# block each other. There's still a single writer at a time (no
# change there), but our app only ever writes from one place
# (the persist transaction) so that's fine.
#
# WAL is *sticky*: once enabled, the choice is persisted in the
# database header. Subsequent connections see WAL automatically. The
# event listener below is therefore a no-op for already-WAL DBs and
# only matters on the very first connection to a freshly-created DB.
@event.listens_for(engine, "connect")
def _enable_sqlite_wal_mode(dbapi_connection, connection_record):
    """Set per-connection SQLite PRAGMAs at the start of every session."""
    # Only applies to SQLite — guard so the same engine module can be
    # reused unchanged when we eventually migrate to Postgres.
    if engine.url.get_backend_name() != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        # `synchronous=NORMAL` is the WAL-recommended setting:
        # crash-safe for the database, slightly looser than FULL for
        # the WAL file itself (a recent commit can be lost on power
        # loss but the DB stays consistent). For our workload, the
        # WAL file is reset on the next checkpoint so the practical
        # risk is minimal.
        cursor.execute("PRAGMA synchronous=NORMAL")
    except Exception as exc:
        _logger.warning(
            "[engine] failed to set SQLite PRAGMAs on new connection: %s", exc,
        )
    finally:
        cursor.close()
