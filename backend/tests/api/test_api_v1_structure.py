from __future__ import annotations

"""Contract tests for API v1 structure (v8.2).

These tests ensure that the versioned API module (app.api.v1) exists,
provides a composition router, and does not execute engine logic or touch
the database when imported.
"""

from importlib import import_module

from fastapi import APIRouter


def test_api_v1_modules_are_importable() -> None:
    v1 = import_module("app.api.v1")
    snapshots = import_module("app.api.v1.snapshots")
    diff = import_module("app.api.v1.diff")
    impact = import_module("app.api.v1.impact")
    reasoning = import_module("app.api.v1.reasoning")
    health = import_module("app.api.v1.health")

    assert hasattr(v1, "v1_router")
    for mod in (snapshots, diff, impact, reasoning, health):
        assert hasattr(mod, "router")
        assert isinstance(mod.router, APIRouter)


def test_api_v1_import_has_no_engine_side_effects() -> None:
    """Importing v1 modules must not run engines or create data.

    This is validated indirectly by asserting that engine symbols are not
    exposed at module level.
    """

    modules = [
        import_module("app.api.v1"),
        import_module("app.api.v1.snapshots"),
        import_module("app.api.v1.diff"),
        import_module("app.api.v1.impact"),
        import_module("app.api.v1.reasoning"),
        import_module("app.api.v1.health"),
    ]

    forbidden = [
        "Snapshot",
        "DiffEngine",
        "build_graph_for_snapshot",
        "compute_downstream_impact",
        "TaisaClient",
    ]

    for mod in modules:
        contents = dir(mod)
        assert all(name not in contents for name in forbidden)


def test_api_v1_router_is_versioned_and_composable() -> None:
    v1 = import_module("app.api.v1")
    core_router = import_module("app.api.router")

    assert isinstance(v1.v1_router, APIRouter)
    assert v1.v1_router.prefix == core_router.API_V1_PREFIX

    # The version identifier is managed centrally in app.api.router
    # and not hard-coded in endpoint logic.
