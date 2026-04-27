"""DDL Generator — produces SQL statements from detected structural changes.

Given a ChangeEvent (with before_state/after_state), generates the
appropriate DDL (ALTER TABLE, CREATE VIEW, DROP, etc.).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def generate_ddl_for_change(
    change_type: str,
    object_type: str,
    object_identifier: str,
    before_state: Optional[Dict[str, Any]],
    after_state: Optional[Dict[str, Any]],
) -> List[str]:
    """Return a list of SQL DDL statements for a single change event."""

    # object_identifier is SCION's canonical dotted path:
    #   "schema"                 → SCHEMA-level change
    #   "schema.table"           → TABLE-level change
    #   "schema.table.column"    → COLUMN-level change
    # We destructure once at the top so every branch below can pick the
    # parts it needs without re-parsing. "public" is the sensible default
    # schema when the identifier is unexpectedly short.
    parts = object_identifier.split(".")
    schema = parts[0] if len(parts) >= 1 else "public"
    table = parts[1] if len(parts) >= 2 else None
    column = parts[2] if len(parts) >= 3 else None

    qualified_table = f"{schema}.{table}" if table else schema

    statements: List[str] = []

    # Below: one branch per change_type. The generated SQL is intentionally
    # ANSI-leaning rather than Teradata-specific — the output is advisory,
    # meant to be reviewed by a DBA before running. When state is missing
    # we emit TODO markers instead of guessing.
    if change_type == "TABLE_ADDED":
        cols = ""
        if after_state and "columns" in after_state:
            col_defs = []
            for c in after_state["columns"]:
                nullable = "" if c.get("nullable", True) else " NOT NULL"
                col_defs.append(f"    {c['column_name']} {c['data_type']}{nullable}")
            cols = ",\n".join(col_defs)
        obj = after_state.get("object_type", "TABLE") if after_state else "TABLE"
        if obj == "VIEW":
            statements.append(f"CREATE VIEW {qualified_table} AS\n    SELECT * FROM <source>;  -- TODO: define view query")
        else:
            if cols:
                statements.append(f"CREATE TABLE {qualified_table} (\n{cols}\n);")
            else:
                statements.append(f"CREATE TABLE {qualified_table} (\n    -- columns to be defined\n);")

    elif change_type == "TABLE_REMOVED":
        obj = before_state.get("object_type", "TABLE") if before_state else "TABLE"
        statements.append(f"DROP {obj} IF EXISTS {qualified_table};")

    elif change_type == "TABLE_TYPE_CHANGED":
        # No RDBMS supports "ALTER TABLE … BECOME VIEW" — the only portable
        # implementation is DROP + recreate. We emit a comment banner first
        # so a reviewer can't miss the destructive nature of this migration.
        old_type = before_state.get("object_type", "TABLE") if before_state else "TABLE"
        new_type = after_state.get("object_type", "VIEW") if after_state else "VIEW"
        statements.append(f"-- Object type changed from {old_type} to {new_type}")
        statements.append(f"DROP {old_type} IF EXISTS {qualified_table};")
        if new_type == "VIEW":
            statements.append(f"CREATE VIEW {qualified_table} AS\n    SELECT * FROM <source>;  -- TODO: define view query")
        else:
            statements.append(f"CREATE TABLE {qualified_table} (\n    -- recreate with appropriate columns\n);")

    elif change_type == "COLUMN_ADDED":
        if column and after_state:
            dtype = after_state.get("data_type", "VARCHAR(255)")
            nullable = "" if after_state.get("nullable", True) else " NOT NULL"
            statements.append(f"ALTER TABLE {qualified_table} ADD {column} {dtype}{nullable};")
        else:
            col_name = parts[-1] if len(parts) >= 3 else "new_column"
            statements.append(f"ALTER TABLE {qualified_table} ADD {col_name} VARCHAR(255);")

    elif change_type == "COLUMN_REMOVED":
        col_name = column or (parts[-1] if len(parts) >= 3 else "unknown_column")
        statements.append(f"ALTER TABLE {qualified_table} DROP COLUMN {col_name};")

    elif change_type == "COLUMN_TYPE_CHANGED":
        col_name = column or (parts[-1] if len(parts) >= 3 else "unknown_column")
        old_type = before_state.get("data_type", "?") if before_state else "?"
        new_type = after_state.get("data_type", "?") if after_state else "?"
        statements.append(f"-- Column type change: {old_type} -> {new_type}")
        statements.append(f"ALTER TABLE {qualified_table} ALTER COLUMN {col_name} SET DATA TYPE {new_type};")

    elif change_type == "COLUMN_NULLABILITY_CHANGED":
        col_name = column or (parts[-1] if len(parts) >= 3 else "unknown_column")
        new_nullable = after_state.get("nullable", True) if after_state else True
        if new_nullable:
            statements.append(f"ALTER TABLE {qualified_table} ALTER COLUMN {col_name} DROP NOT NULL;")
        else:
            statements.append(f"ALTER TABLE {qualified_table} ALTER COLUMN {col_name} SET NOT NULL;")

    elif change_type == "COLUMN_POSITION_CHANGED":
        # Column reordering is NOT natively supported on most warehouses
        # (including Teradata) — it usually requires a full table rebuild
        # via CREATE AS + rename. We deliberately produce only a commented
        # MySQL-style template rather than an executable statement, so the
        # generated file can't accidentally run a destructive operation.
        col_name = column or (parts[-1] if len(parts) >= 3 else "unknown_column")
        new_pos = after_state.get("ordinal_position", "?") if after_state else "?"
        statements.append(f"-- Column position changed to {new_pos} (requires table rebuild in most RDBMS)")
        statements.append(f"-- ALTER TABLE {qualified_table} MODIFY {col_name} ... AFTER <preceding_column>;")

    elif change_type == "SCHEMA_ADDED":
        statements.append(f"CREATE SCHEMA IF NOT EXISTS {schema};")

    elif change_type == "SCHEMA_REMOVED":
        # CASCADE is required on most engines to drop a non-empty schema;
        # we intentionally make this explicit so the destructive intent is
        # visible when the generated DDL is reviewed.
        statements.append(f"DROP SCHEMA IF EXISTS {schema} CASCADE;")

    else:
        statements.append(f"-- Unsupported change type: {change_type} on {object_identifier}")

    return statements


def generate_ddl_for_diff(changes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate DDL for a full list of changes.

    Returns a list of dicts with change metadata + generated SQL.
    """
    results = []
    for ch in changes:
        stmts = generate_ddl_for_change(
            change_type=ch.get("change_type", ""),
            object_type=ch.get("object_type", ""),
            object_identifier=ch.get("object_identifier", ""),
            before_state=ch.get("before_state"),
            after_state=ch.get("after_state"),
        )
        results.append({
            "change_id": ch.get("change_id"),
            "object_identifier": ch.get("object_identifier", ""),
            "change_type": ch.get("change_type", ""),
            "severity": ch.get("severity", "LOW"),
            "is_breaking": ch.get("is_breaking", False),
            "ddl_statements": stmts,
            "ddl_combined": "\n".join(stmts),
        })
    return results
