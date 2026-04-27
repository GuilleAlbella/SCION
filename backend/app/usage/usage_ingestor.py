"""JSON ingestion for usage data from external parser."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.db.engine import engine
from app.usage.usage_models import UsageEvent


def ingest_usage_json(data: List[Dict[str, Any]]) -> int:
    """Ingest a list of usage records from parser JSON.

    Expected format per item:
    {
        "object_name": "schema.table",     # required
        "object_type": "TABLE",            # optional
        "schema_name": "schema",           # optional
        "query_count": 1500,               # optional, default 0
        "user_count": 12,                  # optional, default 0
        "last_accessed": "2026-04-10...",  # optional ISO datetime
        "source": "teradata_query_log",    # optional
        ...any extra fields stored in source_json
    }

    Returns the number of records ingested.
    """

    if not isinstance(data, list):
        raise ValueError("Expected a list of usage records")

    # Ingestion is intentionally lenient: we silently skip malformed
    # entries (non-dict rows, missing object_name) rather than aborting
    # the whole batch. The upstream parser can emit best-effort data and
    # still land the rest of the valid records.
    count = 0
    with Session(engine) as session:
        with session.begin():
            for item in data:
                if not isinstance(item, dict):
                    continue

                # object_name is the only hard requirement — everything
                # else has a reasonable default or is nullable.
                object_name = item.get("object_name")
                if not object_name:
                    continue

                # Parse ISO-8601 timestamps defensively: bad timestamps
                # should not poison the row — we just drop last_accessed
                # and keep the (more important) query/user counts.
                last_accessed = None
                raw_ts = item.get("last_accessed")
                if isinstance(raw_ts, str):
                    try:
                        last_accessed = datetime.fromisoformat(raw_ts)
                    except ValueError:
                        pass

                session.add(UsageEvent(
                    object_name=object_name,
                    object_type=item.get("object_type"),
                    schema_name=item.get("schema_name"),
                    query_count=item.get("query_count", 0),
                    user_count=item.get("user_count", 0),
                    last_accessed=last_accessed,
                    source=item.get("source"),
                    # Store the raw input dict verbatim as source_json so we
                    # retain any provider-specific fields that weren't
                    # mapped to first-class columns. This is the audit trail.
                    source_json=item,
                ))
                count += 1

    return count
