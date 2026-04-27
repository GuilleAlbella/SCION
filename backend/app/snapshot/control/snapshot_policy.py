from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, Any


@dataclass
class SnapshotPolicy:
    """Encapsulate simple snapshot execution rules.

    The policy itself is pure and side-effect free. It only inspects the
    provided in-memory snapshot representations and decides whether a new
    snapshot is allowed according to the configured rules.
    """

    allow_duplicate_descriptions: bool = False
    baseline_unique: bool = True

    def can_execute(
        self,
        *,
        source_system: str,
        description: str,
        is_baseline: bool,
        existing_snapshots: List[Mapping[str, Any]],
    ) -> bool:
        """Return True if a new snapshot may be executed under this policy.

        Args:
            source_system: Logical identifier of the source system.
            description: Human-readable description for the new snapshot.
            is_baseline: Whether the new snapshot is a baseline.
            existing_snapshots: In-memory representation of existing snapshots
                for the same source system. Each item is expected to expose
                at least ``description`` and ``is_baseline`` fields, either
                via attribute access or mapping-style access.
        """

        # Normalise access to support both ORM objects and plain dicts.
        def _get(obj: Any, key: str, default: Any = None) -> Any:
            if isinstance(obj, Mapping):
                return obj.get(key, default)
            return getattr(obj, key, default)

        # Rule 1 – Baseline único por source.
        if self.baseline_unique and is_baseline:
            for snap in existing_snapshots:
                if bool(_get(snap, "is_baseline", False)):
                    return False

        # Rule 2 – Descripción duplicada.
        if not self.allow_duplicate_descriptions:
            for snap in existing_snapshots:
                if _get(snap, "description") == description:
                    return False

        return True
