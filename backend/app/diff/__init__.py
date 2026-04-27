"""Diff engine package (v5.1 structural skeleton).

This package currently exposes a minimal, structural diff engine API and
associated data models. It does not implement real diff logic yet; all
behavioural extensions are deferred to future versions.
"""

from app.diff.diff_engine import DiffEngine
from app.diff.diff_models import Change

__all__ = [
    "DiffEngine",
    "Change",
]
