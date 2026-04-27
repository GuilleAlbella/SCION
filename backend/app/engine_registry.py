from __future__ import annotations

"""Centralised runtime engine registry for SCION.

This module is responsible for creating and holding long-lived engine
instances that back the API surface. Engines are initialised eagerly during
application startup so that:

- System readiness is deterministic.
- Failures in engine wiring are detected before the API starts serving
  requests.
- API endpoints reuse shared instances instead of constructing engines on
  demand.

The registry itself is intentionally thin and contains no FastAPI-specific
logic so that it can be imported from any runtime context (API, CLI, tests).
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

from app.db.engine import engine as db_engine
from app.diff.diff_engine import DiffEngine
from app.graph.graph_engine import GraphEngine
from app.snapshot.orchestrator import SnapshotOrchestrator
from app.taisa.taisa_client import TaisaClient


logger = logging.getLogger("scion.engine_registry")


@dataclass
class EngineRegistry:
    """Hold singletons for all core SCION engines.

    Instances are created explicitly via :func:`initialise_engines` and are not
    constructed lazily on first use.
    """

    snapshot_orchestrator: Optional[SnapshotOrchestrator] = field(default=None)
    diff_engine: Optional[DiffEngine] = field(default=None)
    graph_engine: Optional[GraphEngine] = field(default=None)
    taisa_client: Optional[TaisaClient] = field(default=None)

    # Readiness flags -----------------------------------------------------------------
    #
    # These flags are updated during initialisation and can be inspected by
    # lightweight diagnostics endpoints (such as /health) without touching the
    # actual engines.

    database_ready: bool = field(default=False, init=False)
    snapshot_ready: bool = field(default=False, init=False)
    diff_ready: bool = field(default=False, init=False)
    graph_ready: bool = field(default=False, init=False)
    taisa_ready: bool = field(default=False, init=False)

    initialised: bool = field(default=False, init=False)


# Module-level singleton. Imported everywhere via the get_* accessors below
# rather than accessed directly, so tests can swap the instance if needed
# and callers cannot accidentally bypass the readiness checks.
_registry = EngineRegistry()


def initialise_engines() -> None:
    """Eagerly construct all core engines.

    This function is intended to be invoked exactly once during application
    startup. If any engine fails to construct, the exception is propagated and
    application startup is aborted (fail-fast behaviour).
    """

    if _registry.initialised:
        # Idempotency guard; avoid re-initialising engines if the startup hook
        # is triggered multiple times in a given process.
        logger.info("Engine registry already initialised; skipping re-init.")
        return

    logger.info("[startup] Initialising SCION system engines …")

    # 0. Database connectivity (minimal readiness check).
    logger.info("[startup] Verifying database connectivity …")
    try:
        # A trivial connect/close cycle is enough to surface misconfigured URLs
        # or unreachable database servers without running heavy workloads.
        with db_engine.connect() as connection:  # type: ignore[unused-variable]
            pass
    except Exception:
        logger.exception("[startup] Database connectivity check failed.")
        # Propagate the exception to abort application startup.
        raise

    _registry.database_ready = True
    logger.info("[startup] Database connectivity verified.")

    # ──── Engine construction order ────
    # Order is deliberate: DB must be up before the snapshot layer, snapshot
    # before diff (diff reads snapshot rows), diff before graph (graph
    # consumes change events), and TAISA last since it depends on all of
    # them indirectly via its context builder.
    # 1. Snapshot orchestrator (depends on database engine and metadata layer).
    logger.info("[startup] Initialising snapshot engine (orchestrator)…")
    snapshot_orchestrator = SnapshotOrchestrator(engine=db_engine, engine_name="sqlite")
    _registry.snapshot_ready = True
    logger.info("[startup] Snapshot engine initialised.")

    # 2. Diff engine (pure orchestrator over the ORM / SQLAlchemy engine).
    logger.info("[startup] Initialising diff engine…")
    diff_engine = DiffEngine()
    _registry.diff_ready = True
    logger.info("[startup] Diff engine initialised.")

    # 3. Graph / impact engine skeleton.
    logger.info("[startup] Initialising graph/impact engine…")
    graph_engine = GraphEngine()
    _registry.graph_ready = True
    logger.info("[startup] Graph/impact engine initialised.")

    # 4. TAISA client (reasoning engine, mock/stub implementation for now).
    logger.info("[startup] Initialising TAISA reasoning engine (client)…")
    taisa_client = TaisaClient()
    _registry.taisa_ready = True
    logger.info("[startup] TAISA reasoning engine initialised.")

    _registry.snapshot_orchestrator = snapshot_orchestrator
    _registry.diff_engine = diff_engine
    _registry.graph_engine = graph_engine
    _registry.taisa_client = taisa_client
    _registry.initialised = True

    logger.info("[startup] All SCION engines initialised successfully. System ready.")


def get_engine_states() -> Dict[str, bool]:
    """Return a read-only snapshot of engine readiness flags.

    This helper is intentionally lightweight so that diagnostics endpoints can
    inspect the current state without importing or touching the concrete
    engine instances.
    """

    return {
        "initialised": _registry.initialised,
        "database_ready": _registry.database_ready,
        "snapshot_ready": _registry.snapshot_ready,
        "diff_ready": _registry.diff_ready,
        "graph_ready": _registry.graph_ready,
        "taisa_ready": _registry.taisa_ready,
    }


def _ensure_initialised() -> None:
    """Raise ``RuntimeError`` if ``initialise_engines`` has not been called."""
    if not _registry.initialised:
        raise RuntimeError(
            "Engine registry has not been initialised. "
            "Ensure 'initialise_engines' is called during application startup."
        )


def get_snapshot_orchestrator() -> SnapshotOrchestrator:
    """Return the shared ``SnapshotOrchestrator``.

    Raises:
        RuntimeError: If the registry is uninitialised or the engine is stopped.
    """
    _ensure_initialised()
    if not _registry.snapshot_ready or _registry.snapshot_orchestrator is None:
        raise RuntimeError("Snapshot engine is stopped or not ready.")
    return _registry.snapshot_orchestrator


def get_diff_engine() -> DiffEngine:
    """Return the shared ``DiffEngine``.

    Raises:
        RuntimeError: If the registry is uninitialised or the engine is stopped.
    """
    _ensure_initialised()
    if not _registry.diff_ready or _registry.diff_engine is None:
        raise RuntimeError("Diff engine is stopped or not ready.")
    return _registry.diff_engine


def get_graph_engine() -> GraphEngine:
    """Return the shared ``GraphEngine``.

    Raises:
        RuntimeError: If the registry is uninitialised or the engine is stopped.
    """
    _ensure_initialised()
    if not _registry.graph_ready or _registry.graph_engine is None:
        raise RuntimeError("Graph/impact engine is stopped or not ready.")
    return _registry.graph_engine


def get_taisa_client() -> TaisaClient:
    """Return the shared ``TaisaClient``.

    Raises:
        RuntimeError: If the registry is uninitialised or the client is stopped.
    """
    _ensure_initialised()
    if not _registry.taisa_ready or _registry.taisa_client is None:
        raise RuntimeError("TAISA client is stopped or not ready.")
    return _registry.taisa_client


# stop_engine / restart_engine form the control-plane API surface: they
# allow an operator to take a single engine offline (e.g. revoke TAISA
# access for a demo) without bouncing the whole uvicorn process.
def stop_engine(engine_name: str) -> None:
    """Logically stop a specific engine without shutting down the process.

    This toggles readiness flags (and, for engines other than metadata,
    discards the corresponding instance) so that subsequent calls fail fast
    with a clear error. It is intended for operational control via the control
    API, not for normal application flow.
    """

    name = engine_name.lower()

    # The metadata/DB case only flips the ready flag because the SQLAlchemy
    # engine is a shared module-level object — actually tearing it down
    # would break every other engine. The other engines nil out the
    # instance so readers fail fast with a clear RuntimeError.
    if name == "metadata":
        _registry.database_ready = False
        logger.info("[control] Metadata/DB marked as not ready by control plane.")
    elif name == "snapshot":
        _registry.snapshot_ready = False
        _registry.snapshot_orchestrator = None
        logger.info("[control] Snapshot engine stopped by control plane.")
    elif name == "diff":
        _registry.diff_ready = False
        _registry.diff_engine = None
        logger.info("[control] Diff engine stopped by control plane.")
    elif name in {"impact", "graph"}:
        _registry.graph_ready = False
        _registry.graph_engine = None
        logger.info("[control] Graph/impact engine stopped by control plane.")
    elif name == "taisa":
        _registry.taisa_ready = False
        _registry.taisa_client = None
        logger.info("[control] TAISA reasoning engine stopped by control plane.")
    else:
        raise ValueError(f"Unknown engine name: {engine_name}")


def restart_engine(engine_name: str) -> None:
    """Restart a specific engine in-place using the shared DB engine.

    This reconstructs the selected engine and updates its readiness flag. It
    does not restart the FastAPI/uvicorn process.
    """

    name = engine_name.lower()

    if name == "metadata":
        # Minimal connectivity check to mark DB as ready again.
        logger.info("[control] Restarting metadata/DB connectivity …")
        with db_engine.connect() as connection:  # type: ignore[unused-variable]
            pass
        _registry.database_ready = True
        logger.info("[control] Metadata/DB marked as ready by control plane.")
    elif name == "snapshot":
        logger.info("[control] Restarting snapshot engine …")
        _registry.snapshot_orchestrator = SnapshotOrchestrator(
            engine=db_engine,
            engine_name="sqlite",
        )
        _registry.snapshot_ready = True
        logger.info("[control] Snapshot engine restarted.")
    elif name == "diff":
        logger.info("[control] Restarting diff engine …")
        _registry.diff_engine = DiffEngine()
        _registry.diff_ready = True
        logger.info("[control] Diff engine restarted.")
    elif name in {"impact", "graph"}:
        logger.info("[control] Restarting graph/impact engine …")
        _registry.graph_engine = GraphEngine()
        _registry.graph_ready = True
        logger.info("[control] Graph/impact engine restarted.")
    elif name == "taisa":
        logger.info("[control] Restarting TAISA reasoning engine …")
        _registry.taisa_client = TaisaClient()
        _registry.taisa_ready = True
        logger.info("[control] TAISA reasoning engine restarted.")
    else:
        raise ValueError(f"Unknown engine name: {engine_name}")
