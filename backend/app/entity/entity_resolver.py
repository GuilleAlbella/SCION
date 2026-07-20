"""§2.9 Integration Model — entity resolution.

resolve_entities(snapshot_id, session)
    Upserts ObjectEntity rows for every table/view in the snapshot and
    back-fills entity_id FK columns on:
        table_snapshot, graph_node, usage_event, change_event

Resolution key: (entity_type, object_name) where object_name is the
fully-qualified "SCHEMA.TABLE" string.  node_uid is intentionally NOT used
as the key — its format is inconsistent between SnapshotEngine
("table:SCHEMA.TABLE") and graph_builder ("TABLE:SCHEMA.TABLE:1").

Called from dict_persister.run_post_ingest_pipeline() as the last step.
Also callable standalone for backfill (see backend/tools/backfill_entities.py).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models.entity import ObjectEntity
from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.graph.graph_models import GraphNode
from app.usage.usage_models import UsageEvent
from app.diff.diff_models import ChangeEvent

logger = logging.getLogger(__name__)


def resolve_entities(snapshot_id: int, session: Session) -> int:
    """Upsert ObjectEntity rows for all tables in snapshot_id.

    Back-fills entity_id on table_snapshot, graph_node, usage_event,
    and change_event (for change_events where snapshot_to == snapshot_id).

    Returns the count of entity rows created or updated.
    """
    now = datetime.now(timezone.utc)
    resolved = 0

    # ── Step 1: upsert entity rows from table_snapshot ──────────────
    rows = (
        session.execute(
            select(
                TableSnapshot.table_id,
                TableSnapshot.table_name,
                TableSnapshot.object_type,
                SchemaSnapshot.schema_name,
            )
            .join(SchemaSnapshot, TableSnapshot.schema_id == SchemaSnapshot.schema_id)
            .where(SchemaSnapshot.snapshot_id == snapshot_id)
        )
        .all()
    )

    for table_id, table_name, object_type, schema_name in rows:
        object_name = f"{schema_name}.{table_name}"
        entity_type = (object_type or "TABLE").upper()

        entity = session.execute(
            select(ObjectEntity).where(
                ObjectEntity.entity_type == entity_type,
                ObjectEntity.object_name == object_name,
            )
        ).scalar_one_or_none()

        if entity is None:
            entity = ObjectEntity(
                entity_type=entity_type,
                schema_name=schema_name,
                object_name=object_name,
                first_seen_snapshot_id=snapshot_id,
                last_seen_snapshot_id=snapshot_id,
                is_active=True,
                created_at=now,
            )
            session.add(entity)
            session.flush()
            resolved += 1
        else:
            entity.last_seen_snapshot_id = snapshot_id
            entity.is_active = True

        # Back-fill FK on table_snapshot
        session.execute(
            update(TableSnapshot)
            .where(TableSnapshot.table_id == table_id)
            .values(entity_id=entity.entity_id)
        )

    session.flush()

    # ── Step 2: back-fill entity_id on graph_node ───────────────────
    node_rows = session.execute(
        select(GraphNode.node_id, GraphNode.object_type, GraphNode.schema_name, GraphNode.object_name)
        .where(GraphNode.snapshot_id == snapshot_id)
    ).all()

    for node_id, object_type, schema_name, object_name in node_rows:
        fq_name = f"{schema_name}.{object_name}" if "." not in object_name else object_name
        entity_type = (object_type or "TABLE").upper()

        entity = session.execute(
            select(ObjectEntity).where(
                ObjectEntity.entity_type == entity_type,
                ObjectEntity.object_name == fq_name,
            )
        ).scalar_one_or_none()

        if entity is not None:
            session.execute(
                update(GraphNode)
                .where(GraphNode.node_id == node_id)
                .values(entity_id=entity.entity_id)
            )

    session.flush()

    # ── Step 3: back-fill entity_id on usage_event ──────────────────
    usage_rows = session.execute(
        select(UsageEvent.usage_id, UsageEvent.object_name, UsageEvent.schema_name, UsageEvent.object_type)
        .where(UsageEvent.snapshot_id == snapshot_id, UsageEvent.entity_id.is_(None))
    ).all()

    for usage_id, obj_name, schema_name, object_type in usage_rows:
        fq_name = obj_name if "." in (obj_name or "") else f"{schema_name or ''}.{obj_name or ''}"
        entity_type = (object_type or "TABLE").upper()

        entity = session.execute(
            select(ObjectEntity).where(
                ObjectEntity.entity_type == entity_type,
                ObjectEntity.object_name == fq_name,
            )
        ).scalar_one_or_none()

        if entity is not None:
            session.execute(
                update(UsageEvent)
                .where(UsageEvent.usage_id == usage_id)
                .values(entity_id=entity.entity_id)
            )

    session.flush()

    # ── Step 4: back-fill entity_id on change_event ─────────────────
    change_rows = session.execute(
        select(ChangeEvent.change_id, ChangeEvent.object_identifier, ChangeEvent.object_type)
        .where(ChangeEvent.snapshot_to == snapshot_id, ChangeEvent.entity_id.is_(None))
    ).all()

    for change_id, object_identifier, object_type in change_rows:
        entity_type = (object_type or "TABLE").upper()

        entity = session.execute(
            select(ObjectEntity).where(
                ObjectEntity.entity_type == entity_type,
                ObjectEntity.object_name == object_identifier,
            )
        ).scalar_one_or_none()

        if entity is not None:
            session.execute(
                update(ChangeEvent)
                .where(ChangeEvent.change_id == change_id)
                .values(entity_id=entity.entity_id)
            )

    logger.info(
        "[entity-resolver] snapshot=%s upserted=%d graph_nodes=%d usage_events=%d change_events=%d",
        snapshot_id,
        resolved,
        len(node_rows),
        len(usage_rows),
        len(change_rows),
    )
    return resolved
