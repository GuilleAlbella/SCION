from __future__ import annotations

"""Shared dependency definitions for the API layer.

This module hosts small, composable helpers used by the HTTP API for
cross-cutting concerns (e.g. security) while keeping engines and business
logic decoupled.
"""

from typing import Optional

import os

from fastapi import HTTPException, Request, status


API_KEY_ENV_NAME = "API_KEY"
API_KEY_HEADER_NAME = "X-API-Key"


def _get_configured_api_key() -> Optional[str]:
    """Return the configured API key, or None if security is disabled.

    When ``API_KEY`` is not present in the environment, the API key check is
    considered disabled (DEV / TEST mode) and all requests are allowed.
    """

    return os.getenv(API_KEY_ENV_NAME)


async def require_api_key(request: Request) -> None:
    """Minimal API key security guard for protected endpoints.

    Behaviour:

    - If ``API_KEY`` is **not** set in the environment → allow all requests.
    - If ``API_KEY`` is set:
      - Missing ``X-API-Key`` header → HTTP 401.
      - Invalid ``X-API-Key`` value → HTTP 403.
      - Correct value → request is allowed.
    """

    configured_key = _get_configured_api_key()
    if not configured_key:
        # Security is disabled (DEV / TEST). Allow request.
        return

    provided_key = request.headers.get(API_KEY_HEADER_NAME)
    if provided_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    if provided_key != configured_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    # On success, simply return; the dependency has no return value.
