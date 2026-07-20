"""Centralised logging configuration for SCION.

Switches between compact text (local/dev) and structured JSON (production)
based on the LOG_FORMAT env var.  JSON output is one record per line and
compatible with Loki, CloudWatch, Datadog, and most log aggregators.

Usage:
    from app.logging_config import configure_logging
    configure_logging()   # call once, at application start

Environment variables:
    LOG_LEVEL   — root log level (default: info)
    LOG_FORMAT  — "json" (default) | "text"
"""
from __future__ import annotations

import logging
import logging.config
import os

_LEVEL  = os.getenv("LOG_LEVEL",  "info").upper()
_FORMAT = os.getenv("LOG_FORMAT", "json").lower()

# Loggers whose handlers we configure explicitly so they stay in sync with
# the root handler and don't duplicate output.
_MANAGED_LOGGERS = ["uvicorn", "uvicorn.error", "uvicorn.access"]


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
        "root": {"level": _LEVEL, "handlers": ["stdout"]},
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
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                "rename_fields": {
                    "asctime":   "timestamp",
                    "levelname": "level",
                    "name":      "logger",
                },
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            }
        },
        "handlers": {
            "stdout": {
                "class":     "logging.StreamHandler",
                "formatter": "json",
                "stream":    "ext://sys.stdout",
            }
        },
        "root": {"level": _LEVEL, "handlers": ["stdout"]},
        "loggers": {
            name: {"level": _LEVEL, "handlers": ["stdout"], "propagate": False}
            for name in _MANAGED_LOGGERS
        },
    }


def configure_logging() -> None:
    """Apply logging configuration. Idempotent — safe to call multiple times."""
    if _FORMAT == "json":
        try:
            logging.config.dictConfig(_json_config())
            return
        except Exception:
            # python-json-logger not available — fall back to text silently.
            pass
    logging.config.dictConfig(_text_config())
