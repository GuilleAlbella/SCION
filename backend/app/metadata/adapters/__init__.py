"""Engine-specific adapters that render logical metadata templates into SQL.

Each adapter is stateless and responsible only for turning templates into
engine-specific, read-only SQL strings. No execution or I/O is performed here.
"""

from __future__ import annotations

from .base import BaseAdapter
from .sqlite import SQLiteAdapter
from .postgres import PostgresAdapter
from .teradata import TeradataAdapter

__all__ = [
    "BaseAdapter",
    "SQLiteAdapter",
    "PostgresAdapter",
    "TeradataAdapter",
]
