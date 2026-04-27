"""Static configuration of snapshot template sets.

Template sets define which logical metadata operations are executed as part of
an individual snapshot run. They are explicit, ordered collections of template
names and intentionally avoid any form of dynamic discovery.
"""

from __future__ import annotations

from typing import Tuple

# Default snapshot template set used by the MVP implementation. The order of
# operations is significant and must be preserved.
DEFAULT_SNAPSHOT_TEMPLATE_SET: Tuple[str, ...] = (
    "list_schemas",
    "list_tables",
    "list_columns",
)

# Alias for clarity when targeting SQLite-based snapshots in examples or
# higher-level orchestration code.
SQLITE_SNAPSHOT_TEMPLATE_SET: Tuple[str, ...] = DEFAULT_SNAPSHOT_TEMPLATE_SET
