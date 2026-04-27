"""Boundary tests for SnapshotEngine as a public WS component.

These tests do not validate persistence details; they focus on the public
contract, isolation from unrelated concerns (diff/lineage/reasoning), and
forward-compatibility expectations for upper layers (API/CLI).
"""

from __future__ import annotations

import inspect
from types import ModuleType

from sqlalchemy import select

from app.snapshot.snapshot_engine import SnapshotEngine
from app.snapshot.snapshot_loader import SnapshotLoader
from app.metadata.adapters.sqlite import SQLiteAdapter

from app.db.engine import engine
from app.db.base import Base
from app.db.models.snapshot import Snapshot


def _reset_db() -> None:
    """Drop and recreate all tables for a clean test database."""

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_snapshot_engine_public_invocation_contract() -> None:
    """SnapshotEngine must be invocable as a black-box by upper layers.

    The caller should only need to instantiate SnapshotEngine with a loader
    and call `create_snapshot(...)`, receiving a snapshot_id, without
    touching repositories, sessions, or adapter internals.
    """

    _reset_db()

    adapter = SQLiteAdapter()
    loader = SnapshotLoader(adapter)
    engine_ws = SnapshotEngine(loader)

    snapshot_id = engine_ws.create_snapshot(
        source_system="test_ws",
        description="Boundary contract test",
    )

    assert isinstance(snapshot_id, int)
    assert snapshot_id > 0


def test_snapshot_engine_isolation_from_diff_and_lineage_imports() -> None:
    """SnapshotEngine module must not import diff/lineage/reasoning modules.

    This is enforced by inspecting the source of the module and asserting
    that import statements do not reference disallowed domains.
    """

    import app.snapshot.snapshot_engine as snapshot_engine_module  # type: ignore

    module: ModuleType = snapshot_engine_module
    source = inspect.getsource(module)

    forbidden_tokens = ("diff", "lineage", "taisa", "reason")
    import_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith("import ")
        or line.strip().startswith("from ")
    ]

    for line in import_lines:
        lowered = line.lower()
        assert not any(token in lowered for token in forbidden_tokens), (
            f"SnapshotEngine must not import diff/lineage/reasoning modules: {line!r}"
        )


def test_snapshot_engine_forward_compatibility_for_simple_callers() -> None:
    """Simulate a future caller (API/CLI) that only talks to SnapshotEngine.

    The caller constructs a minimal SnapshotEngine instance and invokes
    `create_snapshot` without needing to be aware of repositories,
    validators, or internal wiring details.
    """

    _reset_db()

    def run_snapshot(source_system: str, description: str) -> int:
        local_engine = SnapshotEngine(SnapshotLoader(SQLiteAdapter()))
        return local_engine.create_snapshot(
            source_system=source_system,
            description=description,
        )

    snapshot_id = run_snapshot("api_caller", "Forward compatibility test")

    assert isinstance(snapshot_id, int)
    assert snapshot_id > 0

    # Optionally verify that the snapshot row exists without coupling to
    # detailed persistence behavior.
    with engine.connect() as conn:
        rows = conn.execute(select(Snapshot)).fetchall()
    assert any(row.snapshot_id == snapshot_id for row in rows)


def test_snapshot_engine_explicit_non_responsibility() -> None:
    """SnapshotEngine must not expose diff/lineage/analysis responsibilities.

    The public API surface of SnapshotEngine is expected to remain focused on
    snapshot creation. Methods or attributes related to diff, lineage, or
    analysis must not appear on the class.
    """

    public_attrs = [name for name in dir(SnapshotEngine) if not name.startswith("_")]
    lowered = " ".join(public_attrs).lower()

    forbidden_keywords = ("diff", "lineage", "analy", "reason")
    assert not any(keyword in lowered for keyword in forbidden_keywords), (
        "SnapshotEngine must not expose diff/lineage/analysis-related methods "
        "or attributes."
    )
