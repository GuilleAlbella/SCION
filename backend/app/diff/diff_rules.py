"""Diff rules for structural diff engine.

v5.8 extracts the comparison logic for schemas, tables, and columns out of
``DiffEngine`` so that the engine focuses on orchestration while this module
encapsulates the rules for *what* constitutes a change.

These functions are **pure**:

- They do not touch the database.
- They have no side effects.
- They operate only on normalized in-memory structures provided by the
  caller and return a list of ``Change`` objects.

Behaviour is intentionally aligned with the v5.2–v5.4 implementations so that
all existing tests and outputs remain unchanged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from app.diff.diff_models import Change

# ── Severity and breaking classification ────────────────────────────────
# The severity tiers feed into UI colouring, alerting policies, and the
# Intelligence Metrics layer. Additions default to LOW (non-destructive),
# removals and type changes are HIGH (destructive / likely breaking).
# Nullability and position are MEDIUM/LOW because they may or may not
# break consumers depending on how queries are written.

SEVERITY_MAP: Dict[str, str] = {
    "TABLE_REMOVED": "HIGH",
    "SCHEMA_REMOVED": "HIGH",
    "COLUMN_REMOVED": "HIGH",
    "TABLE_TYPE_CHANGED": "HIGH",
    "COLUMN_TYPE_CHANGED": "MEDIUM",
    "COLUMN_NULLABILITY_CHANGED": "MEDIUM",
    # §2.4 DDL timestamp merge: the object exists in both snapshots but its
    # DDL definition was modified (last_alter_timestamp advanced). This covers
    # views, stored procedures, macros, and triggers — objects whose internal
    # logic can change without affecting the column list.
    "TABLE_DDL_CHANGED": "MEDIUM",
    "TABLE_ADDED": "LOW",
    "COLUMN_ADDED": "LOW",
    "COLUMN_POSITION_CHANGED": "LOW",
    "SCHEMA_ADDED": "LOW",
}

# A change is "breaking" if downstream consumers SHOULD expect failures
# (dropped column referenced in SELECT, incompatible type cast, etc.).
# Additive changes are never breaking. Nullability/position are not listed
# here because they are context-dependent and not guaranteed to break.
BREAKING_CHANGES: Set[str] = {
    "TABLE_REMOVED",
    "COLUMN_REMOVED",
    "COLUMN_TYPE_CHANGED",
    "SCHEMA_REMOVED",
    "TABLE_TYPE_CHANGED",
}

# Maps each directional change type to its inverse (ADDED↔REMOVED).
# Symmetric types (TYPE_CHANGED, NULLABILITY_CHANGED, POSITION_CHANGED)
# are not listed — they map to themselves and need no inversion.
REVERSE_CHANGE_TYPE: Dict[str, str] = {
    "TABLE_ADDED": "TABLE_REMOVED",
    "TABLE_REMOVED": "TABLE_ADDED",
    "SCHEMA_ADDED": "SCHEMA_REMOVED",
    "SCHEMA_REMOVED": "SCHEMA_ADDED",
    "COLUMN_ADDED": "COLUMN_REMOVED",
    "COLUMN_REMOVED": "COLUMN_ADDED",
}


def get_severity(change_type: str) -> str:
    """Return severity level for a change type."""
    return SEVERITY_MAP.get(change_type, "LOW")


def is_breaking(change_type: str) -> bool:
    """Return whether a change type is considered breaking."""
    return change_type in BREAKING_CHANGES


def diff_schemas(schemas_from: Set[str], schemas_to: Set[str]) -> List[Change]:
    """Compute schema-level changes between two snapshots.

    - Schemas present only in ``schemas_to`` → ``SCHEMA_ADDED``.
    - Schemas present only in ``schemas_from`` → ``SCHEMA_REMOVED``.
    """

    # Pure set arithmetic: schemas are identified only by name, so membership
    # difference fully captures add/remove. There is no rename detection.
    added = schemas_to - schemas_from
    removed = schemas_from - schemas_to

    changes: List[Change] = []

    for name in added:
        changes.append(
            Change(
                object_type="SCHEMA",
                object_identifier=name,
                change_type="SCHEMA_ADDED",
                before_state=None,
                after_state={"schema_name": name},
            )
        )

    for name in removed:
        changes.append(
            Change(
                object_type="SCHEMA",
                object_identifier=name,
                change_type="SCHEMA_REMOVED",
                before_state={"schema_name": name},
                after_state=None,
            )
        )

    return changes


def diff_tables(
    tables_from: Dict[Tuple[str, str], str],
    tables_to: Dict[Tuple[str, str], str],
    *,
    timestamps_from: Optional[Dict[Tuple[str, str], Optional[datetime]]] = None,
    timestamps_to: Optional[Dict[Tuple[str, str], Optional[datetime]]] = None,
) -> List[Change]:
    """Compute table-level changes using the natural key ``(schema, table)``.

    - Present only in ``tables_to`` → ``TABLE_ADDED``.
    - Present only in ``tables_from`` → ``TABLE_REMOVED``.
    - Present in both with different ``object_type`` → ``TABLE_TYPE_CHANGED``.
    - Present in both with same ``object_type`` but different non-null
      ``ddl_alter_timestamp`` → ``TABLE_DDL_CHANGED`` (§2.4).

    The ``timestamps_*`` params are optional dicts of ``ddl_alter_timestamp``
    keyed by ``(schema_name, table_name)``.  When absent or when either side
    has a ``None`` timestamp for a given object, the DDL-change check is skipped
    (NULL means "not known" — we don't infer a change from absence of data).
    """

    ts_from = timestamps_from or {}
    ts_to = timestamps_to or {}

    changes: List[Change] = []

    # Iterate the union so we process tables present in either side exactly
    # once. The three-way branch below then classifies each by presence.
    all_keys: Set[Tuple[str, str]] = set(tables_from) | set(tables_to)

    for schema_name, table_name in all_keys:
        key = (schema_name, table_name)
        in_from = key in tables_from
        in_to = key in tables_to

        qualified_name = f"{schema_name}.{table_name}"

        if in_from and not in_to:
            changes.append(
                Change(
                    object_type="TABLE",
                    object_identifier=qualified_name,
                    change_type="TABLE_REMOVED",
                    before_state={
                        "schema_name": schema_name,
                        "table_name": table_name,
                        "object_type": tables_from[key],
                    },
                    after_state=None,
                )
            )
        elif in_to and not in_from:
            changes.append(
                Change(
                    object_type="TABLE",
                    object_identifier=qualified_name,
                    change_type="TABLE_ADDED",
                    before_state=None,
                    after_state={
                        "schema_name": schema_name,
                        "table_name": table_name,
                        "object_type": tables_to[key],
                    },
                )
            )
        elif in_from and in_to:
            type_from = tables_from[key]
            type_to = tables_to[key]
            if type_from != type_to:
                changes.append(
                    Change(
                        object_type="TABLE",
                        object_identifier=qualified_name,
                        change_type="TABLE_TYPE_CHANGED",
                        before_state={"object_type": type_from},
                        after_state={"object_type": type_to},
                    )
                )
            else:
                # §2.4 DDL timestamp merge: same object type on both sides —
                # check whether the DDL definition itself changed.  Only fires
                # when BOTH sides carry a non-null timestamp so we never infer
                # a change from missing data.
                ddl_ts_from = ts_from.get(key)
                ddl_ts_to = ts_to.get(key)
                if ddl_ts_from and ddl_ts_to and ddl_ts_from != ddl_ts_to:
                    changes.append(
                        Change(
                            object_type="TABLE",
                            object_identifier=qualified_name,
                            change_type="TABLE_DDL_CHANGED",
                            before_state={
                                "object_type": type_from,
                                "ddl_alter_timestamp": ddl_ts_from.isoformat(),
                            },
                            after_state={
                                "object_type": type_to,
                                "ddl_alter_timestamp": ddl_ts_to.isoformat(),
                            },
                        )
                    )

    return changes


def diff_columns(
    *,
    common_tables: Set[Tuple[str, str]],
    columns_from: Dict[Tuple[str, str, str], Tuple[str, bool, int]],
    columns_to: Dict[Tuple[str, str, str], Tuple[str, bool, int]],
) -> List[Change]:
    """Compute column-level changes for tables present in both snapshots.

    Uses the natural key ``(schema_name, table_name, column_name)`` and emits
    separate ``Change`` instances for type, nullability, and position
    differences, matching v5.4 behaviour exactly.
    """

    changes: List[Change] = []

    # Fast-exit when there are no tables present in both snapshots: there
    # is no valid context in which a column-level diff would be meaningful.
    if not common_tables:
        return changes

    all_keys: Set[Tuple[str, str, str]] = set(columns_from) | set(columns_to)

    for schema_name, table_name, column_name in all_keys:
        key = (schema_name, table_name, column_name)
        in_from = key in columns_from
        in_to = key in columns_to

        # Only consider columns for tables that are common to both snapshots.
        # Columns of ADDED/REMOVED tables are already implied by the table
        # change — skipping avoids noisy duplicate events.
        table_key = (schema_name, table_name)
        if table_key not in common_tables:
            continue

        qualified_name = f"{schema_name}.{table_name}.{column_name}"

        if in_from and not in_to:
            data_type, nullable, ordinal_position = columns_from[key]
            changes.append(
                Change(
                    object_type="COLUMN",
                    object_identifier=qualified_name,
                    change_type="COLUMN_REMOVED",
                    before_state={
                        "data_type": data_type,
                        "nullable": nullable,
                        "ordinal_position": ordinal_position,
                    },
                    after_state=None,
                )
            )
        elif in_to and not in_from:
            data_type, nullable, ordinal_position = columns_to[key]
            changes.append(
                Change(
                    object_type="COLUMN",
                    object_identifier=qualified_name,
                    change_type="COLUMN_ADDED",
                    before_state=None,
                    after_state={
                        "data_type": data_type,
                        "nullable": nullable,
                        "ordinal_position": ordinal_position,
                    },
                )
            )
        elif in_from and in_to:
            # For columns present on both sides, we emit a SEPARATE change
            # per differing attribute (type, nullability, position). This
            # lets severity rules and impact analysis treat them independently
            # rather than bundling them into one opaque "COLUMN_CHANGED" event.
            data_from, nullable_from, pos_from = columns_from[key]
            data_to, nullable_to, pos_to = columns_to[key]

            if data_from != data_to:
                changes.append(
                    Change(
                        object_type="COLUMN",
                        object_identifier=qualified_name,
                        change_type="COLUMN_TYPE_CHANGED",
                        before_state={"data_type": data_from},
                        after_state={"data_type": data_to},
                    )
                )

            if nullable_from != nullable_to:
                changes.append(
                    Change(
                        object_type="COLUMN",
                        object_identifier=qualified_name,
                        change_type="COLUMN_NULLABILITY_CHANGED",
                        before_state={"nullable": nullable_from},
                        after_state={"nullable": nullable_to},
                    )
                )

            if pos_from != pos_to:
                changes.append(
                    Change(
                        object_type="COLUMN",
                        object_identifier=qualified_name,
                        change_type="COLUMN_POSITION_CHANGED",
                        before_state={"ordinal_position": pos_from},
                        after_state={"ordinal_position": pos_to},
                    )
                )

    return changes

