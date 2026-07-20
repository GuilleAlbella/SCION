"""Migrate all data from a SQLite SCION database to a Postgres instance.

Usage (lab — run inside the backend container):
    # 1. Copy the SQLite file into the container:
    #    docker cp kalido_lite.db scion-lab-backend:/tmp/scion_source.db
    #
    # 2. Run this script:
    #    docker exec scion-lab-backend python backend/tools/migrate_sqlite_to_postgres.py

Usage (production — SSH into the server, then):
    #    docker exec scion-backend python backend/tools/migrate_sqlite_to_postgres.py \\
    #        --source sqlite:////data/scion.db \\
    #        --target postgresql+psycopg://scion:<password>@postgres:5432/scion

Arguments:
    --source   SQLAlchemy URL for the source SQLite DB
               Default: sqlite:////tmp/scion_source.db
    --target   SQLAlchemy URL for the target Postgres DB
               Default: reads DATABASE_URL env var (set by docker-compose)
    --batch    Rows per INSERT batch (default 500)
    --dry-run  Print row counts per table without copying anything

How it works:
    1. Connects to both DBs.
    2. Verifies the target is at HEAD (alembic_version must match source).
    3. Iterates tables in FK-dependency order (Base.metadata.sorted_tables).
    4. Copies rows in batches with SQLAlchemy Core — no ORM overhead.
    5. Resets Postgres sequences so future INSERTs don't collide with migrated IDs.

Notes:
    - The target DB must already have the schema applied (run db_init.py init first).
    - The target is expected to be EMPTY. The script aborts if any table already
      has rows, to prevent double-migration accidents.
    - alembic_version is NOT copied — the target's own version record is kept.
    - JSON columns (node_metadata, edge_metadata) round-trip correctly through
      SQLAlchemy's JSON type without any special handling.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

# ──── Path bootstrap ────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_PATH = PROJECT_ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [migrate] %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger("migrate")


DEFAULT_SOURCE = "sqlite:////tmp/scion_source.db"


def _build_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Migrate SCION data from SQLite to Postgres.")
    p.add_argument("--source",   default=DEFAULT_SOURCE,             help="Source SQLite URL")
    p.add_argument("--target",   default=os.environ.get("DATABASE_URL"), help="Target Postgres URL")
    p.add_argument("--batch",    type=int, default=500,              help="Rows per INSERT batch")
    p.add_argument("--dry-run",  action="store_true",                help="Count rows only, no writes")
    return p.parse_args()


def _connect(url: str, label: str):
    from sqlalchemy import create_engine, text
    _log.info("Connecting to %s: %s", label, url)
    engine = create_engine(url, echo=False, future=True)
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    _log.info("%s connection OK.", label)
    return engine


def _alembic_version(engine) -> Optional[str]:
    from sqlalchemy import inspect, text
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as c:
        row = c.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
    return row[0] if row else None


def _check_target_empty(engine, tables) -> list[str]:
    """Return names of non-empty tables in target."""
    from sqlalchemy import text
    non_empty = []
    with engine.connect() as c:
        for t in tables:
            count = c.execute(text(f'SELECT COUNT(*) FROM "{t.name}"')).scalar()
            if count:
                non_empty.append(f"{t.name} ({count} rows)")
    return non_empty


def _reset_sequences(engine, tables) -> None:
    """Advance Postgres sequences to max(id) so future inserts don't collide."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    for table in tables:
        pk_cols = list(table.primary_key.columns)
        if len(pk_cols) != 1:
            continue
        pk = pk_cols[0]
        if str(pk.type).upper() not in ("INTEGER", "BIGINT", "SERIAL", "BIGSERIAL"):
            continue
        # Each sequence gets its own transaction so a missing sequence name
        # doesn't abort the rest of the resets.
        try:
            with engine.begin() as c:
                max_val = c.execute(
                    text(f'SELECT MAX("{pk.name}") FROM "{table.name}"')
                ).scalar()
                if max_val is None:
                    continue
                seq = f"{table.name}_{pk.name}_seq"
                c.execute(text(f"SELECT setval('{seq}', :v)"), {"v": max_val})
                _log.info("  sequence %-50s → %d", seq, max_val)
        except Exception:
            # Sequence may not exist (FK columns, UUID PKs, renamed sequences).
            pass


def main() -> int:
    args = _build_args()

    if not args.target:
        _log.error("--target is required (or set DATABASE_URL env var).")
        return 2

    if "sqlite" in args.target.lower():
        _log.error("Target looks like SQLite — this script migrates TO Postgres only.")
        return 2

    src_engine = _connect(args.source, "SOURCE (SQLite)")
    tgt_engine = _connect(args.target, "TARGET (Postgres)")

    # ── Alembic version check ────────────────────────────────────────────────
    src_ver = _alembic_version(src_engine)
    tgt_ver = _alembic_version(tgt_engine)
    _log.info("Source alembic version : %s", src_ver or "<none>")
    _log.info("Target alembic version : %s", tgt_ver or "<none>")
    if src_ver and tgt_ver and src_ver != tgt_ver:
        _log.error(
            "Version mismatch — source is at %s, target is at %s. "
            "Run `db_init.py init` on the target to bring it to HEAD, "
            "or ensure you are migrating from the latest source backup.",
            src_ver, tgt_ver,
        )
        return 2

    # ── Load all ORM models so Base.metadata is complete ────────────────────
    from app.db.base import Base  # noqa: side-effect imports

    # sorted_tables respects FK dependency order (parents before children).
    tables = [
        t for t in Base.metadata.sorted_tables
        if t.name != "alembic_version"
    ]

    # ── Dry-run: count only ──────────────────────────────────────────────────
    if args.dry_run:
        _log.info("DRY RUN — counting source rows per table:")
        total = 0
        with src_engine.connect() as sc:
            from sqlalchemy import text
            for t in tables:
                n = sc.execute(text(f'SELECT COUNT(*) FROM "{t.name}"')).scalar()
                if n:
                    _log.info("  %-45s %d rows", t.name, n)
                    total += n
        _log.info("Total rows to migrate: %d", total)
        return 0

    # ── Safety check: target must be empty ──────────────────────────────────
    non_empty = _check_target_empty(tgt_engine, tables)
    if non_empty:
        _log.error("Target is NOT empty — aborting to prevent double-migration.")
        _log.error("Non-empty tables: %s", ", ".join(non_empty))
        _log.error("If you want to re-migrate, drop and recreate the target DB first.")
        return 2

    # ── Migrate table by table ───────────────────────────────────────────────
    # Postgres enforces FK constraints via triggers. SQLite doesn't, so source
    # data may contain orphaned rows. We disable triggers on each table before
    # inserting (the table owner is allowed to do this) and re-enable after,
    # preserving data as-is and letting the application deal with orphans later.
    from sqlalchemy import text

    total_rows = 0
    orphans_skipped = 0
    t0 = time.monotonic()

    with src_engine.connect() as sc:
        for table in tables:
            # Count source rows first.
            src_count = sc.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar()
            if src_count == 0:
                continue

            _log.info("%-45s %6d rows …", table.name, src_count)
            copied = 0
            offset = 0

            while True:
                rows = sc.execute(
                    text(f'SELECT * FROM "{table.name}" LIMIT {args.batch} OFFSET {offset}')
                ).mappings().fetchall()
                if not rows:
                    break

                with tgt_engine.begin() as tc:
                    # Disable FK trigger checks for this table so orphaned rows
                    # (possible in SQLite where FK enforcement is off by default)
                    # are copied faithfully without raising IntegrityErrors.
                    tc.execute(text(f'ALTER TABLE "{table.name}" DISABLE TRIGGER ALL'))
                    tc.execute(table.insert(), [dict(r) for r in rows])
                    tc.execute(text(f'ALTER TABLE "{table.name}" ENABLE TRIGGER ALL'))

                copied += len(rows)
                offset += args.batch

            total_rows += copied
            _log.info("  ✓ %d rows copied", copied)

    # ── Reset Postgres sequences ─────────────────────────────────────────────
    _log.info("Resetting Postgres sequences …")
    _reset_sequences(tgt_engine, tables)

    elapsed = time.monotonic() - t0
    _log.info("Migration complete — %d total rows in %.1fs", total_rows, elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
