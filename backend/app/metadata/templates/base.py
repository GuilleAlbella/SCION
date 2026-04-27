"""Base abstraction for engine-agnostic metadata templates.

These templates describe the logical shape of metadata queries (what to retrieve),
without specifying any engine-specific SQL or execution details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class BaseTemplate:
    """Base template describing the logical shape of a metadata query.

    This abstraction defines what information a template should expose, without
    prescribing how it is rendered or executed against any particular engine.
    """

    template_name: str
    description: str
    output_fields: List[str]
    required_filters: Optional[List[str]] = field(default=None)
