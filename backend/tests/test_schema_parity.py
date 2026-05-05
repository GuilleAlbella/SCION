"""Regression test: ``alembic upgrade head`` must produce the same
schema as ``Base.metadata.create_all()``.

Why this exists
---------------
SCION historically had two parallel paths to schema creation:

  1. ``Base.metadata.create_all()`` — used by tests, by the old
     ``tools/bootstrap_sqlite_db.py``, and (transitively) by anything
     that imported the engine and ran ``create_all`` against it.
  2. ``alembic upgrade head`` — used by anything claiming to track
     migrations.

These can drift: add a model without a migration, and path (1) keeps
working while path (2) silently produces an incomplete schema. Helton
hit exactly this on his first day setting up the project — alembic
gave him a partial DB, ``rich_seed`` then crashed on a missing table,
and the diagnosis took an afternoon.

This test makes the two paths converge in CI. If you add a model
column without a matching migration (or vice versa), this test fails
loudly with the specific drift, before the regression reaches anyone.

What we compare
---------------
Both paths are run against fresh in-memory SQLite databases, then
inspected with SQLAlchemy:

  * **Tables** — set comparison, with ``alembic_version`` excluded
    (only one of the paths creates it).
  * **Columns** — name set per shared table. We don't compare types
    yet because SQLAlchemy's reflection of SQLite types isn't
    perfectly round-trippable (e.g. ``Boolean`` reflects as ``BOOLEAN``
    in metadata but the column dump may say ``BOOLEAN(...)``); the
    Helton-class drift is "missing column", which name comparison
    catches.
  * **Indexes** — name set per shared table. Catches the v1.15.00
    case where indexes were added to models but not to migrations
    (or vice versa).

Failure mode
------------
On drift the test raises ``AssertionError`` with a structured message
listing every difference, organised by table. The intent is that a
developer reading the failure can immediately see what's missing where
without re-running anything.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

# Path bootstrap mirrors conftest.py — tests/ may be invoked from any cwd.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_PATH = PROJECT_ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))


def _apply_alembic_to(url: str) -> None:
    """Run ``alembic upgrade head`` against the URL.

    We import inside the function so that pytest collection doesn't
    pull in alembic at module-load time (it pulls in app code via
    env.py side-effect imports, which is fine for the test but
    needlessly slows import-time when the test isn't being run).
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


def _apply_metadata_to(url: str) -> None:
    """Run ``Base.metadata.create_all`` against the URL.

    Late import for the same reason as ``_apply_alembic_to``: avoids
    pulling app code at collection time, and ensures any DATABASE_URL
    fiddling done above by alembic doesn't bleed into this engine.
    """
    from app.db.base import Base

    engine = create_engine(url, future=True)
    Base.metadata.create_all(bind=engine)
    engine.dispose()


def _inspect_tables(url: str) -> dict[str, dict[str, set[str]]]:
    """Return ``{table: {"columns": {...}, "indexes": {...}}}`` for the URL.

    ``alembic_version`` is excluded since it's an alembic-only artefact
    that the metadata path never produces.
    """
    engine = create_engine(url, future=True)
    try:
        insp = inspect(engine)
        out: dict[str, dict[str, set[str]]] = {}
        for table in insp.get_table_names():
            if table == "alembic_version":
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            idxs = {i["name"] for i in insp.get_indexes(table)}
            out[table] = {"columns": cols, "indexes": idxs}
        return out
    finally:
        engine.dispose()


@pytest.fixture
def two_fresh_dbs(tmp_path):
    """Yield two fresh SQLite URLs — one for each schema-creation path.

    File-backed (not ``:memory:``) because alembic spins up its own
    engine via ``env.py`` and we need both processes pointed at the
    same physical DB. Tmp dir is auto-cleaned by pytest.
    """
    alembic_db = tmp_path / "alembic_head.db"
    metadata_db = tmp_path / "metadata_create_all.db"
    yield (
        f"sqlite:///{alembic_db}",
        f"sqlite:///{metadata_db}",
    )


def test_alembic_head_matches_orm_metadata(two_fresh_dbs):
    """The two schema-creation paths must produce identical schemas."""
    alembic_url, metadata_url = two_fresh_dbs

    _apply_alembic_to(alembic_url)
    _apply_metadata_to(metadata_url)

    alembic_schema = _inspect_tables(alembic_url)
    metadata_schema = _inspect_tables(metadata_url)

    diffs: list[str] = []

    # Table-level drift: any table present in one but not the other is
    # a clear sign of a missing migration (Helton's case) or a stray
    # migration (less common, but possible if someone reverts a model
    # without reverting its migration).
    only_in_alembic = set(alembic_schema) - set(metadata_schema)
    only_in_metadata = set(metadata_schema) - set(alembic_schema)
    if only_in_alembic:
        diffs.append(
            "Tables in alembic HEAD but not in Base.metadata: "
            f"{sorted(only_in_alembic)}"
        )
    if only_in_metadata:
        diffs.append(
            "Tables in Base.metadata but missing from alembic HEAD: "
            f"{sorted(only_in_metadata)}"
        )

    # Per-table column + index drift for the tables they share.
    for table in sorted(set(alembic_schema) & set(metadata_schema)):
        a = alembic_schema[table]
        m = metadata_schema[table]

        col_only_a = a["columns"] - m["columns"]
        col_only_m = m["columns"] - a["columns"]
        if col_only_a:
            diffs.append(
                f"  Table {table}: columns in alembic but not in models: {sorted(col_only_a)}"
            )
        if col_only_m:
            diffs.append(
                f"  Table {table}: columns in models but not in alembic: {sorted(col_only_m)}"
            )

        idx_only_a = a["indexes"] - m["indexes"]
        idx_only_m = m["indexes"] - a["indexes"]
        if idx_only_a:
            diffs.append(
                f"  Table {table}: indexes in alembic but not in models: {sorted(idx_only_a)}"
            )
        if idx_only_m:
            diffs.append(
                f"  Table {table}: indexes in models but not in alembic: {sorted(idx_only_m)}"
            )

    if diffs:
        pretty = "\n".join(diffs)
        raise AssertionError(
            "Schema drift between `alembic upgrade head` and "
            "`Base.metadata.create_all()`:\n"
            f"{pretty}\n\n"
            "If you added a model, write the matching migration. "
            "If you added a migration, ensure the model reflects the change. "
            "Both paths must produce the same schema."
        )
