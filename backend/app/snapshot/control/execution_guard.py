from __future__ import annotations

from typing import List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.snapshot import Snapshot
from app.snapshot.control.snapshot_policy import SnapshotPolicy


class SnapshotExecutionGuard:
    """Read-only guard that enforces snapshot execution policies.

    This guard never performs writes or commits; it only reads existing
    snapshots for a given source system and delegates the decision to a
    ``SnapshotPolicy`` instance.
    """

    def __init__(self, session: Session, policy: SnapshotPolicy):
        self._session = session
        self._policy = policy

    def assert_can_execute(
        self,
        *,
        source_system: str,
        description: str,
        is_baseline: bool,
    ) -> None:
        """Raise if a snapshot cannot be executed under the active policy.

        The method loads existing snapshots for the given ``source_system``,
        passes them to the policy, and raises ``RuntimeError`` when the
        policy blocks execution.
        """

        stmt = select(Snapshot).where(Snapshot.source_system == source_system)
        existing: List[Snapshot] = list(self._session.scalars(stmt))

        allowed = self._policy.can_execute(
            source_system=source_system,
            description=description,
            is_baseline=is_baseline,
            existing_snapshots=existing,
        )

        if not allowed:
            raise RuntimeError("Snapshot execution blocked by policy")
