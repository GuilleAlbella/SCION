"""Execution helpers for running engine-agnostic metadata templates.

This package provides a thin, read-only runner layer that:
- Uses adapters to render logical templates into SQL strings.
- Uses SQLAlchemy Core to execute read-only SELECT statements.
- Enforces read-only semantics before delegating to the database engine.
"""

from __future__ import annotations

from .engine import ExecutionEngine
from .runner import MetadataRunner

__all__ = [
    "ExecutionEngine",
    "MetadataRunner",
]
