#!/usr/bin/env python3
"""§2.9 Integration Model — backfill script.

Runs resolve_entities() for every existing snapshot in chronological order,
populating object_entity rows and entity_id FK columns on:
    table_snapshot, graph_node, usage_event, change_event

Safe to run multiple times — resolve_entities() is idempotent (upsert).

Usage:
    python -m backend.tools.backfill_entities
    python -m backend.tools.backfill_entities --dry-run
    python -m backend.tools.backfill_entities --snapshot-id 5  # single snapshot
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill object_entity rows for all snapshots")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    parser.add_argument("--snapshot-id", type=int, default=None, help="Backfill a single snapshot")
    args = parser.parse_args()

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.engine import engine
    from app.db.models.snapshot import Snapshot
    from app.entity.entity_resolver import resolve_entities

    with Session(bind=engine) as session:
        if args.snapshot_id is not None:
            snaps = session.execute(
                select(Snapshot).where(Snapshot.snapshot_id == args.snapshot_id)
            ).scalars().all()
        else:
            snaps = session.execute(
                select(Snapshot).order_by(Snapshot.snapshot_time)
            ).scalars().all()

    logger.info("Backfilling %d snapshot(s)…", len(snaps))

    total_resolved = 0
    for snap in snaps:
        if args.dry_run:
            logger.info("[DRY-RUN] would resolve entities for snapshot %d (%s)", snap.snapshot_id, snap.snapshot_time)
            continue
        with Session(bind=engine) as session:
            n = resolve_entities(snap.snapshot_id, session)
            session.commit()
        logger.info("Snapshot %d → %d entities resolved", snap.snapshot_id, n)
        total_resolved += n

    if not args.dry_run:
        logger.info("Done. Total entity rows created/updated: %d", total_resolved)


if __name__ == "__main__":
    main()
