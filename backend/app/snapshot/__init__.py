"""Snapshot ingestion workflow for canonical metadata.

This package coordinates extraction of logical metadata, normalization into
canonical structures, and persistence using the existing SQLAlchemy ORM
models. It is intentionally focused on a single-snapshot ingestion workflow
without diff or lineage logic.
"""

from .snapshot_engine import SnapshotEngine
from .snapshot_loader import SnapshotLoader

__all__ = [
    "SnapshotEngine",
    "SnapshotLoader",
]
