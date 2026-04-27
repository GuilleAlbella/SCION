from __future__ import annotations

"""API package for orchestration layer.

This package defines the high-level HTTP API surface of the system.

Design principles (v8.1):
- Stateless: no in-memory state beyond a single request lifecycle.
- Engines as source of truth: snapshot, diff, graph, impact, and TAISA
  engines remain the only place where business/technical logic lives.
- Orchestration only: the API will route requests, validate inputs, and
  delegate to engines; it will not implement core algorithms or persist
  data directly.
- Versioned by path: future routers will live under prefixes such as
  "/api/v1" without relying on header-based versioning.

FastAPI or any other web framework is intentionally *not* initialised in
this module yet; endpoint wiring is introduced in later steps (v8.2+).
"""

from . import router  # re-export router module for convenience

__all__ = ["router"]
