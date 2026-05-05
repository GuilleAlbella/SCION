"""SCION database lifecycle management — single canonical entry point.

Replaces the older split between ``tools/bootstrap_sqlite_db.py``
(``Base.metadata.create_all`` path) and bare ``alembic upgrade head``
invocations. We had two parallel paths to schema creation; whenever a
new ORM model was added without a matching Alembic migration, the
``create_all`` path produced a working schema while ``alembic upgrade
head`` produced a partial one. Helton ran into exactly that on his
first day setting up the project, and the bootstrap script became
"the workaround" rather than the documented path.

This tool collapses both paths into one:

    python backend/tools/db_init.py init           # idempotent
    python backend/tools/db_init.py reset          # destructive (asks)
    python backend/tools/db_init.py seed           # demo data
    python backend/tools/db_init.py reset --with-seed
    python backend/tools/db_init.py init --with-seed

``init`` is the only path used to create or upgrade schema. It detects
three states:

  - **fresh** — no tables present. Runs ``alembic upgrade head`` from
    base. Result: schema at HEAD, ``alembic_version`` populated.

  - **managed** — ``alembic_version`` table exists and has a row. Runs
    ``alembic upgrade head`` (no-op when already at HEAD).

  - **legacy** — tables exist but ``alembic_version`` is empty. This is
    the v1.14.08 / v1.15.00 corner case: a DB created via
    ``Base.metadata.create_all`` (now-removed bootstrap script) before
    the schema-parity test was in place. We compare the actual table
    set against ``Base.metadata`` and, if they match, ``stamp`` the DB
    at HEAD so future migrations chain cleanly. If they don't match,
    we refuse and tell the user to ``reset``.

The schema-parity test (``backend/tests/test_schema_parity.py``)
guarantees that ``Base.metadata.create_all()`` and ``alembic upgrade
head`` produce identical schemas. With that test in CI, the legacy
"stamp at HEAD" branch is mathematically equivalent to running every
migration that bootstrap skipped.

Why we don't ship Postgres / non-SQLite reset support: the destructive
path (``reset``) only knows how to drop the SQLite file. For Postgres
the safe approach (drop+recreate database) requires admin creds we
don't want to embed; users on Postgres should drop the schema
externally and then run ``init``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional


# ──── Path bootstrap ────
# Resolve the project root from this file location so the script works
# regardless of the working directory the user invokes it from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_PATH = PROJECT_ROOT / "backend"
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"

if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))


_logger = logging.getLogger("db_init")


def _check_runtime_deps() -> None:
    """Fail fast with a friendly message when run outside the project venv.

    The most common failure mode is invoking this script with the system
    Python instead of ``.venv/Scripts/python.exe`` — it then ImportErrors
    on ``alembic`` (or sqlalchemy, etc.) with a stack trace that doesn't
    point the user at the actual fix. Catching the import here lets us
    print one-line hint instead.
    """
    missing: list[str] = []
    for mod in ("alembic", "sqlalchemy"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if not missing:
        return

    venv_python = (
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        if os.name == "nt"
        else PROJECT_ROOT / ".venv" / "bin" / "python"
    )
    print(
        "[db_init] Missing required modules: "
        + ", ".join(missing)
        + "\n[db_init] You're probably running with the system Python instead "
        "of the project venv.\n"
        f"[db_init] Try: {venv_python} backend/tools/db_init.py "
        + " ".join(sys.argv[1:] or ["init"]),
        file=sys.stderr,
    )
    sys.exit(2)


def _alembic_cfg(database_url: Optional[str] = None):
    """Build an Alembic ``Config`` pointed at the project's ini file.

    When ``database_url`` is provided, override the ``sqlalchemy.url``
    main option so the migrations target the requested DB instead of the
    one hard-coded in ``alembic.ini``. We need this for the schema-parity
    test (which targets a tmp file) and for any caller that wants to run
    against a non-default location.
    """
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    if database_url is not None:
        cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _engine_state(engine) -> str:
    """Classify the DB into one of {fresh, managed, legacy}.

    See the module docstring for what each state means and how ``init``
    handles them.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    # No tables at all → fresh DB. Includes the case where the SQLite
    # file doesn't even exist yet (SQLAlchemy creates it on first connect).
    non_alembic_tables = tables - {"alembic_version"}
    if not non_alembic_tables and "alembic_version" not in tables:
        return "fresh"

    if "alembic_version" not in tables:
        return "legacy"

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).all()

    return "managed" if rows else "legacy"


def _drift_report(engine) -> tuple[set[str], set[str]]:
    """Diff the DB's actual table list against ``Base.metadata``.

    Returns ``(missing_in_db, extra_in_db)`` — sets of table names. Empty
    sets mean the DB schema matches what ORM models expect; non-empty
    means there's drift and we shouldn't pretend the DB is at HEAD.
    """
    from sqlalchemy import inspect

    # Importing Base triggers the side-effect imports in app/db/base.py
    # which register every model on Base.metadata.
    from app.db.base import Base

    expected = set(Base.metadata.tables.keys())
    actual = set(inspect(engine).get_table_names()) - {"alembic_version"}
    return expected - actual, actual - expected


def _resolve_sqlite_path(database_url: str) -> Optional[Path]:
    """Extract the filesystem path from a SQLite URL, or None for non-SQLite."""
    if not database_url.startswith("sqlite"):
        return None
    # SQLAlchemy's SQLite URLs are 'sqlite:///path' (3 slashes for relative,
    # 4 for absolute on POSIX). Strip the prefix and let pathlib resolve.
    raw = database_url.split("sqlite:///", 1)[1] if "sqlite:///" in database_url else None
    if not raw:
        return None
    return Path(raw).resolve()


# ──── Commands ────


def cmd_init() -> int:
    """Ensure the DB is at HEAD. Idempotent; safe to re-run."""
    from alembic import command

    from app.db.engine import DATABASE_URL, engine

    state = _engine_state(engine)
    cfg = _alembic_cfg(database_url=DATABASE_URL)
    print(f"[db_init] DB at {DATABASE_URL!r} — state: {state}")

    if state == "fresh":
        print("[db_init] Running alembic upgrade head against an empty DB...")
        command.upgrade(cfg, "head")
        print("[db_init] OK — schema created at HEAD.")
        return 0

    if state == "managed":
        print("[db_init] Running alembic upgrade head (no-op if already current)...")
        command.upgrade(cfg, "head")
        print("[db_init] OK — DB at HEAD.")
        return 0

    # state == "legacy": tables exist but alembic doesn't track them.
    # Verify schema parity before claiming HEAD. If the actual schema
    # doesn't match what `Base.metadata.create_all` would produce, we
    # have no safe way to figure out which migrations the legacy DB
    # already has and which it's missing — refuse and tell the user to
    # reset.
    print("[db_init] Legacy state detected (alembic_version empty).")
    missing, extra = _drift_report(engine)
    if missing or extra:
        print("[db_init] ERROR: legacy schema does NOT match Base.metadata.")
        if missing:
            print(f"[db_init]   tables expected by ORM but missing in DB: {sorted(missing)}")
        if extra:
            print(f"[db_init]   tables in DB but not in ORM: {sorted(extra)}")
        print(
            "[db_init] Cannot safely stamp a drifted legacy DB at HEAD. "
            "Either fix the schema manually or run `db_init.py reset` "
            "(this destroys data)."
        )
        return 2

    print("[db_init] Schema matches Base.metadata; stamping at HEAD...")
    command.stamp(cfg, "head")
    # `stamp` only writes the alembic_version row. There may be migrations
    # past HEAD that the legacy DB doesn't have applied (because they
    # added indexes / columns that bootstrap_sqlite_db.py would have
    # created via metadata.create_all). Running upgrade head AFTER the
    # stamp is a no-op for the just-stamped revision but DOES apply any
    # newer pending migrations.
    print("[db_init] Running upgrade head to apply any pending migrations...")
    command.upgrade(cfg, "head")
    print("[db_init] OK — legacy DB now alembic-managed and at HEAD.")
    return 0


def cmd_reset(yes: bool = False) -> int:
    """Wipe the SQLite DB file and recreate via alembic.

    Only supports SQLite — see the module docstring for why. For non-
    SQLite DBs, drop the schema externally and re-run ``init``.
    """
    from app.db.engine import DATABASE_URL, engine

    db_path = _resolve_sqlite_path(DATABASE_URL)
    if db_path is None:
        print(f"[db_init] reset only supports SQLite; got {DATABASE_URL!r}.")
        print("[db_init] Drop the schema externally, then run `db_init.py init`.")
        return 2

    if not yes:
        print(f"[db_init] About to DELETE the database at: {db_path}")
        try:
            resp = input("[db_init] Type 'yes' to confirm: ").strip().lower()
        except EOFError:
            # Non-interactive caller without --yes — refuse rather than
            # silently destroy.
            print("[db_init] Non-interactive run without --yes; aborting.")
            return 1
        if resp != "yes":
            print("[db_init] Aborted.")
            return 1

    # Release any open connections so Windows lets us delete the file.
    # Without dispose(), the engine pool can keep file handles open
    # which makes Path.unlink() fail with PermissionError.
    engine.dispose()

    # Delete the main DB file plus its WAL siblings (if any). WAL files
    # only exist when the DB has been written to since the last
    # checkpoint, but we delete defensively to avoid leaving an orphaned
    # WAL that would attach to a fresh DB on next open.
    deleted: list[Path] = []
    for suffix in ("", "-wal", "-shm", "-journal"):
        candidate = Path(str(db_path) + suffix)
        if candidate.exists():
            try:
                candidate.unlink()
                deleted.append(candidate)
            except OSError as exc:
                print(f"[db_init] WARN: could not delete {candidate}: {exc}")

    if deleted:
        print(f"[db_init] Deleted: {', '.join(str(p) for p in deleted)}")
    else:
        print("[db_init] No DB file present (already gone).")

    return cmd_init()


def cmd_seed() -> int:
    """Run the demo seed against an alembic-managed DB.

    Refuses to run unless ``init`` has been run first — seeding a legacy
    or fresh DB would silently couple seed correctness to whichever
    schema-creation path the seed script happens to invoke internally,
    bringing back exactly the kind of drift this script is trying to
    prevent.
    """
    from app.db.engine import engine

    state = _engine_state(engine)
    if state != "managed":
        print(f"[db_init] Cannot seed: DB is in {state!r} state.")
        print("[db_init] Run `db_init.py init` (or `reset`) first.")
        return 2

    print("[db_init] Running rich_seed.main()...")
    # Late import: rich_seed touches the DB on import via SQLAlchemy
    # session creation. Importing only when we're about to run keeps
    # the dependency graph of `init` and `reset` lean.
    from tools import rich_seed

    rich_seed.main()
    print("[db_init] Seed complete.")
    return 0


# ──── CLI ────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="db_init",
        description=(
            "SCION database lifecycle management. "
            "Run with no arguments for an interactive menu, or pass an "
            "explicit subcommand for scripted use."
        ),
    )
    # `command` is optional: when missing AND running on an interactive
    # terminal, we drop into the menu in `_interactive_menu`. When
    # missing AND non-interactive (CI, piped stdin), we default to
    # `init` for backward compat with scripts that rely on the old
    # implicit-init behaviour.
    parser.add_argument(
        "command",
        nargs="?",
        default=None,
        choices=["init", "reset", "seed"],
        help=(
            "init: ensure DB is at HEAD (idempotent). "
            "reset: drop and recreate the SQLite file. "
            "seed: load demo data. "
            "Omit to get an interactive menu."
        ),
    )
    parser.add_argument(
        "--with-seed",
        action="store_true",
        help="After init/reset, also run the demo seed.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip every confirmation prompt (for scripts/CI).",
    )
    parser.add_argument(
        "--db-url",
        help="Override DATABASE_URL for this invocation.",
    )
    return parser


# Each menu entry is (label, command, with_seed). The order matches the
# numbering printed to the terminal — keep "Cancel" last so an
# accidental Enter-Enter doesn't blow away the DB.
_MENU_OPTIONS: list[tuple[str, Optional[str], bool]] = [
    ("Init / upgrade DB to HEAD (no data changes)", "init", False),
    ("Init + seed demo data", "init", True),
    ("Reset DB (wipe + recreate schema)", "reset", False),
    ("Reset DB + seed demo data", "reset", True),
    ("Seed demo data only (DB must already be at HEAD)", "seed", False),
    ("Cancel", None, False),
]


def _interactive_menu() -> tuple[Optional[str], bool]:
    """Prompt the user to pick an action. Returns ``(command, with_seed)``.

    ``command is None`` means the user cancelled. The caller should
    treat that as a successful exit (return code 0). We do the prompt
    in a tight loop until the user picks a valid option — fat-finger
    mistakes don't crash, they re-prompt.
    """
    print("[db_init] What do you want to do?\n")
    for idx, (label, _cmd, _seed) in enumerate(_MENU_OPTIONS, start=1):
        print(f"  {idx}) {label}")
    print()

    while True:
        try:
            choice = input("[db_init] Choice [1-{}]: ".format(len(_MENU_OPTIONS))).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None, False
        if not choice:
            continue
        try:
            n = int(choice)
        except ValueError:
            print("[db_init] Please enter a number.")
            continue
        if not (1 <= n <= len(_MENU_OPTIONS)):
            print(f"[db_init] Pick a number between 1 and {len(_MENU_OPTIONS)}.")
            continue
        _label, command, with_seed = _MENU_OPTIONS[n - 1]
        return command, with_seed


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _check_runtime_deps()
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Override BEFORE any `app.db.engine` import. The cmd_* functions
    # import the engine lazily, so setting the env var here is enough
    # for the URL change to take effect.
    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url

    # No subcommand → interactive menu (terminal) or default to `init`
    # (non-interactive / CI). `sys.stdin.isatty()` is False under pytest
    # capture, in pipes, and in most CI runners — exactly the cases
    # where we want the script to be non-interactive.
    command = args.command
    with_seed = args.with_seed
    if command is None:
        if sys.stdin.isatty():
            command, menu_with_seed = _interactive_menu()
            if command is None:
                print("[db_init] Cancelled.")
                return 0
            # Menu-driven seeding overrides the flag (the menu is the
            # source of truth when the user came in through it).
            with_seed = with_seed or menu_with_seed
        else:
            command = "init"

    if command == "init":
        rc = cmd_init()
    elif command == "reset":
        rc = cmd_reset(yes=args.yes)
    elif command == "seed":
        # `seed` doesn't combine with --with-seed (would be redundant).
        return cmd_seed()
    else:  # pragma: no cover — argparse already restricted the choices
        return 2

    if rc != 0:
        return rc

    if with_seed:
        return cmd_seed()
    return rc


if __name__ == "__main__":
    sys.exit(main())
