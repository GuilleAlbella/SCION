"""Centralised logging configuration for SCION — §2.8 Production Runtime.

Switches between compact text (local/dev) and structured JSON (production)
based on the LOG_FORMAT env var. JSON output is one record per line and
compatible with Loki, CloudWatch, Datadog, and most log aggregators.

Pure-Python implementation: no pythonjsonlogger dependency.

Usage:
    from app.logging_config import configure_logging
    configure_logging()   # call once, at application start

Environment variables:
    LOG_LEVEL   — root log level (default: info)
    LOG_FORMAT  — "json" (default) | "text"
"""
from __future__ import annotations

import json
import logging
import logging.config
import os
from datetime import datetime, timezone
from typing import Any

# Re-exported so main.py and middleware can reference it without importing
# contextvars directly.
from app.request_context import get_request_id

_LEVEL  = os.getenv("LOG_LEVEL",  "info").upper()
_FORMAT = os.getenv("LOG_FORMAT", "json").lower()

# Loggers whose handlers we configure explicitly so they stay in sync with
# the root handler and don't duplicate output.
_MANAGED_LOGGERS = ["uvicorn", "uvicorn.error", "uvicorn.access"]

# Fields on LogRecord that every record carries and that we DON'T want to
# forward as extra payload — they're either redundant or internal to logging.
_SKIP_FIELDS = frozenset({
    "args", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "message", "module", "msecs", "msg",
    "name", "pathname", "process", "processName", "relativeCreated",
    "stack_info", "taskName", "thread", "threadName",
})


class _ScionJsonFormatter(logging.Formatter):
    """Structured JSON log formatter — no external dependencies.

    Emits one JSON object per line with the shape:
        {
          "timestamp": "2026-08-31T14:32:05Z",
          "level":     "INFO",
          "logger":    "app.api.v1.graph",
          "request_id": "a3f2b1c0",   # from RequestIdMiddleware, when present
          "message":   "...",
          ... extra= kwargs passed by the caller ...
        }
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        payload: dict[str, Any] = {
            "timestamp":  ts,
            "level":      record.levelname,
            "logger":     record.name,
            "message":    record.getMessage(),
        }

        # Include request ID when a request context is active.
        rid = get_request_id()
        if rid:
            payload["request_id"] = rid

        # Forward any extra= kwargs the caller attached, skipping the
        # built-in LogRecord internals.
        for key, val in record.__dict__.items():
            if key not in _SKIP_FIELDS and not key.startswith("_"):
                payload[key] = val

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(payload, default=str)


def _text_config() -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "text": {
                "format":  "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
                "datefmt": "%H:%M:%S",
            }
        },
        "handlers": {
            "stdout": {
                "class":     "logging.StreamHandler",
                "formatter": "text",
                "stream":    "ext://sys.stdout",
            }
        },
        "root":    {"level": _LEVEL, "handlers": ["stdout"]},
        "loggers": {
            name: {"level": _LEVEL, "handlers": ["stdout"], "propagate": False}
            for name in _MANAGED_LOGGERS
        },
    }


def _json_config() -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": _ScionJsonFormatter,
            }
        },
        "handlers": {
            "stdout": {
                "class":     "logging.StreamHandler",
                "formatter": "json",
                "stream":    "ext://sys.stdout",
            }
        },
        "root":    {"level": _LEVEL, "handlers": ["stdout"]},
        "loggers": {
            name: {"level": _LEVEL, "handlers": ["stdout"], "propagate": False}
            for name in _MANAGED_LOGGERS
        },
    }


def configure_logging() -> None:
    """Apply logging configuration. Idempotent — safe to call multiple times."""
    if _FORMAT == "json":
        logging.config.dictConfig(_json_config())
    else:
        logging.config.dictConfig(_text_config())
