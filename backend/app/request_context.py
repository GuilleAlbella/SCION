"""Request-scoped context variables — §2.8 Production Runtime.

Stores per-request state in Python's contextvars so it's available anywhere
in the call stack without threading through function arguments.

Usage (automatic via RequestIdMiddleware in main.py):
    from app.request_context import get_request_id
    rid = get_request_id()   # "a3f2b1c0" or None outside a request
"""
from __future__ import annotations

import contextvars
from typing import Optional

_REQUEST_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)


def set_request_id(value: str) -> None:
    _REQUEST_ID.set(value)


def get_request_id() -> Optional[str]:
    return _REQUEST_ID.get()
