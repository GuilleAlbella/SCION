from __future__ import annotations

"""System / meta endpoints.

Exposes runtime metadata that is not tied to any business engine:

- ``GET /system/version`` — current SCION version vs. latest published
  GitHub release. Powers the "update available" pill in the Sidebar.

The endpoint is deliberately resilient: if GitHub is unreachable or
rate-limits the unauthenticated query, it falls back to returning only
the local version so the UI never blocks on it.
"""

import logging
import os
import re
import threading
import time
from typing import Any

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/system", tags=["system"])

_logger = logging.getLogger(__name__)


# ──── Configuration ────

# The frontend bundle is the source of truth for APP_VERSION (see
# `frontend/src/lib/constants.ts`). At runtime the backend container
# also gets it via the SCION_VERSION env var, baked at image build.
# When unset (dev mode), we fall back to a sentinel so the UI knows
# we're running an untagged checkout.
_DEFAULT_VERSION = os.getenv("SCION_VERSION", "v0.0.0-dev")

# GitHub releases API for the SCION repo. Owner + repo overridable so
# forks don't hit the wrong endpoint.
_GH_OWNER = os.getenv("SCION_GH_OWNER", "GuilleAlbella")
_GH_REPO = os.getenv("SCION_GH_REPO", "SCION")
_GH_LATEST_URL = f"https://api.github.com/repos/{_GH_OWNER}/{_GH_REPO}/releases/latest"

# Cache the GitHub response for 1h. Anonymous requests to the GitHub
# API are rate-limited at 60/h per IP — a single SCION instance with
# many open browser tabs would burn through that in seconds without
# this cache.
_CACHE_TTL_S = 3600

# Cache state (in-process; one container, one process).
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {"fetched_at": 0.0, "payload": None}


# ──── Helpers ────


_VERSION_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:[.-]?(\d+))?")


def _parse_version(s: str | None) -> tuple[int, int, int, int]:
    """Return a comparable tuple from a version string, padding missing
    components with 0 so ``v1.20`` and ``v1.20.0.0`` compare equal.

    Anything that doesn't match the pattern returns ``(0, 0, 0, 0)`` so
    the caller treats it as "behind". This is safer than raising — a
    malformed local version shouldn't break the UI.
    """
    if not s:
        return (0, 0, 0, 0)
    m = _VERSION_RE.search(s)
    if not m:
        return (0, 0, 0, 0)
    parts = [int(m.group(i) or 0) for i in (1, 2, 3, 4)]
    return tuple(parts)  # type: ignore[return-value]


def _fetch_latest() -> dict[str, Any] | None:
    """Hit the GitHub releases API and return the parsed payload, or
    ``None`` when anything goes wrong (404, network, rate limit). The
    caller treats ``None`` as "no update info available right now".
    """
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                _GH_LATEST_URL,
                headers={"Accept": "application/vnd.github+json"},
            )
        if resp.status_code != 200:
            _logger.info("GitHub releases API returned %s", resp.status_code)
            return None
        data = resp.json()
        return {
            "tag": data.get("tag_name"),
            "name": data.get("name"),
            "url": data.get("html_url"),
            "published_at": data.get("published_at"),
        }
    except Exception as exc:  # noqa: BLE001 — UI must never block on this
        _logger.info("GitHub releases lookup failed: %s", exc)
        return None


def _get_latest_cached() -> dict[str, Any] | None:
    now = time.monotonic()
    with _cache_lock:
        if _cache["payload"] is not None and (now - _cache["fetched_at"]) < _CACHE_TTL_S:
            return _cache["payload"]
    fresh = _fetch_latest()
    with _cache_lock:
        _cache["fetched_at"] = now
        _cache["payload"] = fresh
    return fresh


# ──── Routes ────


@router.get("/version")
def get_version() -> dict[str, Any]:
    """Return current vs. latest SCION version and whether an update is
    available.

    Response shape (always 200; never raises to the UI):

        {
          "current":          "v1.20.00",
          "latest":           "v1.21.0"     | null,
          "update_available": true          | false,
          "release_url":      "https://..." | null,
          "release_name":     "..."         | null,
          "published_at":     "..."         | null,
        }
    """
    current = _DEFAULT_VERSION
    latest = _get_latest_cached()

    if latest is None:
        return {
            "current": current,
            "latest": None,
            "update_available": False,
            "release_url": None,
            "release_name": None,
            "published_at": None,
        }

    update_available = _parse_version(latest.get("tag")) > _parse_version(current)
    return {
        "current": current,
        "latest": latest.get("tag"),
        "update_available": update_available,
        "release_url": latest.get("url"),
        "release_name": latest.get("name"),
        "published_at": latest.get("published_at"),
    }
