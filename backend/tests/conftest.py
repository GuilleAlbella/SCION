"""Test configuration for metadata tests.

This module ensures that the backend/ application package is importable when
pytest discovers and runs tests, so that imports like ``from app...`` work
without relying on the working directory or environment configuration.
"""

from __future__ import annotations

import os
import sys

# Compute the project root based on this file location so that the tests do
# not depend on how pytest is invoked (e.g. from the project root or another
# directory). The project root is one level above the "backend" folder.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
BACKEND_PATH = os.path.join(PROJECT_ROOT, "backend")

# Inject the backend/ directory into sys.path before any test imports occur,
# so that ``app`` can be imported as a top-level package within tests.
if BACKEND_PATH not in sys.path:
    sys.path.insert(0, BACKEND_PATH)
