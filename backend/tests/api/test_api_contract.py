from __future__ import annotations

"""Contract tests for the API design (v8.1).

These tests ensure that the API package exists, is importable, and does
not introduce unwanted side effects or tight coupling to engines or
frameworks. No HTTP framework is initialised at this stage.
"""

from importlib import import_module


def test_api_package_is_importable() -> None:
    api_pkg = import_module("app.api")
    assert hasattr(api_pkg, "router")


def test_router_module_defines_versioned_prefix_without_framework() -> None:
    router = import_module("app.api.router")

    # Versioned by path, not by header.
    assert getattr(router, "API_V1_PREFIX", None) == "/api/v1"

    # No FastAPI app should be created yet.
    assert not hasattr(router, "app"), "router must not initialise FastAPI yet"


def test_importing_api_does_not_trigger_business_logic() -> None:
    """Importing the API must not run engines or touch the database.

    This is validated indirectly: the modules are lightweight, contain
    only docstrings and constants, and do not import engine modules.
    """

    api_pkg = import_module("app.api")
    router = import_module("app.api.router")
    deps = import_module("app.api.dependencies")

    # Sanity checks to ensure these modules remain lightweight.
    for mod in (api_pkg, router, deps):
        forbidden = [
            "Snapshot",
            "DiffEngine",
            "build_graph_for_snapshot",
            "compute_downstream_impact",
            "TaisaClient",
        ]
        contents = dir(mod)
        assert all(name not in contents for name in forbidden)
