from __future__ import annotations

"""API v1 router composition.

This module defines the versioned router for API v1. It is responsible for
wiring together the sub-routers for snapshots, diff, impact, reasoning, and
health checks.

No business logic or engine calls are executed here; this module only
composes routers and exposes a versioned entry point for future HTTP
framework wiring.
"""

from fastapi import APIRouter, Depends

from app.api.router import API_V1_PREFIX
from app.api.dependencies import require_api_key
from app.api.v1 import alerts, changes, control, ddl, dict_import, diff, export, graph, health, impact, intelligence, lineage, metrics, notifications, objects, parser_import, reasoning, report, schema_tree, search, share_import, simulation, snapshots, system, timeline, usage


v1_router = APIRouter(prefix=API_V1_PREFIX)

# Attach sub-routers. Security is applied via API key dependency to all
# v1 routes except health, which intentionally remains public for liveness
# checks.
v1_router.include_router(snapshots.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(changes.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(diff.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(graph.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(impact.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(lineage.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(reasoning.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(metrics.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(usage.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(intelligence.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(control.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(ddl.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(alerts.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(export.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(report.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(schema_tree.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(search.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(simulation.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(parser_import.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(dict_import.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(timeline.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(objects.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(notifications.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(share_import.router, dependencies=[Depends(require_api_key)])
v1_router.include_router(health.router)
# /system/version is intentionally public (no API key) so the Sidebar
# pill can render before the user ever authenticates and so the same
# endpoint can be polled by uptime checks.
v1_router.include_router(system.router)

__all__ = ["v1_router"]
