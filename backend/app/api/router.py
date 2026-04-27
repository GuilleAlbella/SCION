from __future__ import annotations

"""API routing configuration (contract only, no framework wiring yet).

This module defines the *shape* of the API layer without binding to a
concrete web framework.

Key design principles (v8.1):

- Stateless
  - No global mutable state or per-process caches.
  - Each HTTP request will be handled independently, relying solely on
    persisted data (snapshots, change_event, graph, impact_event,
    reasoning_event).

- Versioned by path
  - API versions are expressed via path prefixes (e.g. "/api/v1").
  - No version negotiation via HTTP headers.
  - The router must allow co-existence of future versions (v2, v3)
    without refactoring existing code.

- Delegation only
  - The API will not implement snapshot, diff, graph, impact, or TAISA
    logic.
  - It will call the appropriate engine functions and map their
    results into HTTP responses.

- Auditability and testability
  - Each future endpoint should make it possible to trace operations by
    `snapshot_id` and `change_id`.
  - Engines must be mockable so that the API layer can be tested
    without UI or live TAISA.

No FastAPI (or any other HTTP framework) is imported here yet. Concrete
routers and endpoints will be added in v8.2 and v8.3.
"""

# Path prefix for the first public API version.
API_V1_PREFIX = "/api/v1"
