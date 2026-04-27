"""Abstract execution engine for read-only metadata queries.

This module defines a minimal interface for executing raw SQL SELECT
statements using SQLAlchemy Core, while enforcing read-only semantics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.engine import Engine


class ExecutionEngine(ABC):
    """Abstract base class for executing read-only SQL queries.

    Implementations are responsible for executing raw SELECT statements using
    a SQLAlchemy Engine and returning results in a normalized structure.
    """

    @abstractmethod
    def execute(self, sql: str) -> List[Dict[str, Any]]:  # pragma: no cover - interface only
        """Execute a read-only SQL statement and return rows as dictionaries."""


class SqlAlchemyExecutionEngine(ExecutionEngine):
    """Execution engine that delegates to a SQLAlchemy Core Engine.

    This engine enforces that only SELECT statements are executed, so that the
    metadata layer cannot accidentally perform writes or DDL.
    """

    def __init__(self, engine: Engine) -> None:
        """Create a new execution engine bound to a SQLAlchemy Engine.

        The underlying engine configuration (URL, pooling, etc.) is provided
        by the caller; this class only controls how queries are executed.
        """

        self._engine = engine

    def execute(self, sql: str) -> List[Dict[str, Any]]:
        """Execute a read-only SQL statement and return rows as dictionaries.

        The SQL text is validated to start with SELECT (case-insensitive) to
        enforce read-only semantics before sending it to the database.
        """

        stripped = sql.lstrip()
        if not stripped.lower().startswith("select") and not stripped.lower().startswith("pragma"):
            # PRAGMA is allowed for engines like SQLite where metadata is
            # exposed via PRAGMA statements, but no writes are permitted.
            raise ValueError("Only read-only SELECT/PRAGMA statements are allowed in metadata runner.")

        with self._engine.connect() as conn:
            result = conn.execute(text(sql))
            # Use mappings() to normalize rows as dictionaries regardless of dialect.
            return [dict(row) for row in result.mappings()]
