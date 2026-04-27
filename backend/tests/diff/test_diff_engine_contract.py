"""Contract tests for the DiffEngine public API.

These tests verify only the public contract and structural guarantees of the
DiffEngine. They do not assert specific diff *content*, only type, stability,
and boundary safety.
"""

from __future__ import annotations

import inspect
from types import ModuleType

from app.diff.diff_engine import DiffEngine
from app.diff.diff_models import Change


def test_diff_engine_can_be_instantiated_without_dependencies() -> None:
    """DiffEngine must be constructible without any external dependencies."""

    engine = DiffEngine()
    assert isinstance(engine, DiffEngine)


def test_diff_engine_compute_diff_returns_list_of_changes() -> None:
    """compute_diff must return a list of Change instances (or be empty)."""

    engine = DiffEngine()
    result = engine.compute_diff(snapshot_from=1, snapshot_to=2)

    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, Change)


def test_diff_engine_compute_diff_is_idempotent() -> None:
    """Multiple calls with the same inputs must yield the same result."""

    engine = DiffEngine()

    first = engine.compute_diff(10, 20)
    second = engine.compute_diff(10, 20)

    assert first == second


def test_diff_engine_boundary_safety_and_no_side_effects() -> None:
    """Boundary safety: no persistence, no snapshot internals, no side effects.

    v5.2 is allowed to read schema metadata from the snapshot storage, but it
    must not depend on repositories, loaders, or change-event persistence.
    We assert that:
    - The return type is a list of Change (or empty list).
    - The module does not import disallowed persistence or snapshot-internal
      components.
    """

    engine = DiffEngine()
    result = engine.compute_diff(3, 4)

    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, Change)

    # Inspect the diff_engine module to ensure no forbidden imports exist.
    import app.diff.diff_engine as diff_engine_module  # type: ignore

    module: ModuleType = diff_engine_module
    source = inspect.getsource(module)

    forbidden_tokens = ("repository", "loader", "change_event")
    import_lines = [
        line.strip()
        for line in source.splitlines()
        if line.strip().startswith("import ")
        or line.strip().startswith("from ")
    ]

    for line in import_lines:
        lowered = line.lower()
        assert not any(token in lowered for token in forbidden_tokens), (
            f"DiffEngine must not import DB or snapshot internals in v5.1: {line!r}"
        )


def test_diff_engine_rejects_identical_snapshots() -> None:
    """compute_diff must reject identical snapshot identifiers.

    This ensures callers are explicit about the comparison direction and
    protects against accidental self-diff calls.
    """

    engine = DiffEngine()

    try:
        engine.compute_diff(5, 5)
    except ValueError:
        # Expected for identical identifiers.
        return

    raise AssertionError("compute_diff should raise ValueError for identical snapshots")
