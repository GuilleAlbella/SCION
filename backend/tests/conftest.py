"""Test configuration for the SCION backend test suite.

Two responsibilities, both load-bearing:

1. **Make the `app` package importable.** Inject `backend/` into
   `sys.path` so tests can do `from app... import ...` regardless of
   the working directory pytest is invoked from.

2. **Redirect the global SQLAlchemy engine to a throwaway DB file
   BEFORE any test imports it.** Most tests under `backend/tests/`
   (diff/, snapshot/, graph/, api/, taisa/) import the global engine
   from `app.db.engine` and call `Base.metadata.drop_all/create_all`
   against it. Without redirection, those tests wipe the developer's
   working `kalido_lite.db` — including the rich-seed demo data and
   any imported customer snapshots. We learned that the hard way in
   v1.13.04: a casual `pytest backend/tests/` torched the demo DB.

   The fix: set `DATABASE_URL` to a session-scoped temp SQLite
   *before* `app.db.engine` ever reads `os.environ["DATABASE_URL"]`.
   Since the engine is constructed at module import time, this env
   var must be set in `conftest.py` (loaded by pytest before any
   `test_*.py`) — putting it in a fixture would be too late.

   The temp DB is created under `tempfile.gettempdir()` so it
   survives across processes (some sub-tests spawn their own) but
   gets cleaned up on session end. We do NOT use `tmp_path` because
   that's per-test and we want one shared DB across the whole run
   (consistent with how the existing tests behave when they hit the
   global engine).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# ──── 1. Make `app` importable ────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
BACKEND_PATH = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_PATH not in sys.path:
    sys.path.insert(0, BACKEND_PATH)


# ──── 2. Redirect engine away from the developer's working DB ────
# DO NOT remove or move below the `app.db.engine` import — order matters.
# The env var must be set BEFORE that module is first imported anywhere
# (including transitively by other test modules).

def _ensure_test_database_url() -> None:
    """Set `DATABASE_URL` to a per-session SQLite file under tempdir.

    If `DATABASE_URL` is already set (e.g. CI uses an env-injected
    test DB), respect it — we only intervene when nothing's been
    configured, which is the dangerous default.
    """
    if os.environ.get("DATABASE_URL"):
        # Caller has explicitly set a DB; trust them.
        return

    # `gettempdir()` is per-OS-user, persisted across the test run, and
    # auto-cleaned by the OS over time. Per-pid filename so concurrent
    # `pytest -n auto` runs don't trample each other.
    tmp_path = Path(tempfile.gettempdir()) / f"scion_pytest_{os.getpid()}.db"

    # Wipe any stale file from a previous interrupted run so we start
    # with a clean slate. Failure to delete (e.g. file is locked
    # because a previous run crashed mid-write) is non-fatal — the
    # engine's `create_all` will overwrite the schema anyway.
    if tmp_path.exists():
        try:
            tmp_path.unlink()
        except OSError:
            pass

    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path}"


_ensure_test_database_url()


# ──── 3. Sanity guard: refuse to run if engine still points at prod-ish DB ──
# Defence in depth. If something above silently fails (e.g. a future
# refactor moves the env-var setting), we don't want pytest to silently
# fall back to the developer's working DB. This check runs after the
# env is set; if the engine ends up pointing at something that looks
# like a project-root SQLite file, abort the test run loudly.

def pytest_configure(config) -> None:  # noqa: D401  -- pytest hook
    """Pytest startup hook. Verifies the engine is NOT pointed at the
    developer's working `kalido_lite.db`. Aborts the run if it is."""
    # Late import: by now, env is set and the engine module can be
    # safely loaded. Importing earlier would lock in the wrong URL.
    from app.db.engine import DATABASE_URL  # type: ignore

    forbidden_paths = [
        os.path.join(PROJECT_ROOT, "kalido_lite.db"),
        os.path.join(PROJECT_ROOT, "backend", "kalido_lite.db"),
    ]
    # Normalise for case-insensitive comparison on Windows.
    norm_url = os.path.normcase(DATABASE_URL)
    for fp in forbidden_paths:
        if os.path.normcase(fp) in norm_url:
            raise RuntimeError(
                f"REFUSING TO RUN TESTS: engine is pointed at the "
                f"developer's working DB ({fp}). The test suite calls "
                f"drop_all/create_all on the global engine and would "
                f"wipe your demo data. Check that `DATABASE_URL` is "
                f"unset and that `_ensure_test_database_url` ran."
            )
