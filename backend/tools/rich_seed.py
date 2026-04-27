"""Rich demo seed for SCION UI (v1.06 — "sabroso" edition).

Produces a fat, realistic banking EDW with:
  - **10 snapshots** covering a 30-day window
  - Full **Teradata data type catalog** (numeric, character, binary, datetime,
    interval, LOB, spatial, period, complex)
  - **All 10+ change types** produced at least once across the timeline:
    SCHEMA_ADDED, SCHEMA_REMOVED, TABLE_ADDED, TABLE_REMOVED,
    TABLE_TYPE_CHANGED, COLUMN_ADDED, COLUMN_REMOVED, COLUMN_TYPE_CHANGED,
    COLUMN_NULLABILITY_CHANGED, COLUMN_POSITION_CHANGED.

Snapshots are computed as mutations on top of the previous snapshot — each
one tells a small story (rollout, widening, refactor, decommission, etc.)
so the diff page, impact pages, and criticality scorecard all have
something to show.

Usage (backend can keep running — this script only DELETEs demo rows, it
does not drop the DB file, so no need to stop `.\\dev.ps1`):
    cd backend
    ../.venv/Scripts/python.exe tools/rich_seed.py
"""

from __future__ import annotations

import copy
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Tuple

# ──── Path setup ────
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir, os.pardir))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.db.models.snapshot import Snapshot
from app.db.models.schema_snapshot import SchemaSnapshot
from app.db.models.table_snapshot import TableSnapshot
from app.db.models.column_snapshot import ColumnSnapshot
from app.diff.diff_engine import DiffEngine
from app.graph.graph_builder import build_graph_for_snapshot
from app.graph.graph_metrics import persist_node_metrics
from app.snapshot.structural_hash import compute_structural_hash
from app.snapshot.snapshot_metrics import compute_snapshot_metrics
from app.usage.usage_ingestor import ingest_usage_json
from app.usage.criticality_engine import compute_criticality
from app.graph.graph_diff_linker import link_changes_to_graph
from app.graph.impact_analyzer import compute_downstream_impact, compute_upstream_impact
from app.graph.impact_persister import persist_impact_events
from app.diff.diff_models import ChangeEvent


# ───────────────────────────────────────────────────────────────────────
# Teradata data type catalog — covers every category a Teradata 17.x–20.x
# DBA would reasonably encounter in production. Grouped semantically so
# the baseline can pull a realistic mix per column domain.
# ───────────────────────────────────────────────────────────────────────
TERADATA_TYPES: Dict[str, List[str]] = {
    "integer":   ["BYTEINT", "SMALLINT", "INTEGER", "BIGINT"],
    "decimal":   ["DECIMAL(5,2)", "DECIMAL(10,2)", "DECIMAL(18,2)",
                  "DECIMAL(20,6)", "NUMERIC(12,4)", "NUMBER(10)"],
    "float":     ["FLOAT", "REAL", "DOUBLE PRECISION"],
    "char":      ["CHAR(2)", "CHAR(3)", "CHAR(10)", "CHAR(36)"],
    "varchar":   ["VARCHAR(20)", "VARCHAR(50)", "VARCHAR(100)",
                  "VARCHAR(255)", "VARCHAR(500)", "VARCHAR(4000)"],
    "long_text": ["CLOB", "LONG VARCHAR"],
    "binary":    ["BYTE(16)", "VARBYTE(256)", "BLOB"],
    "date":      ["DATE"],
    "time":      ["TIME", "TIME(6)", "TIME WITH TIME ZONE"],
    "timestamp": ["TIMESTAMP", "TIMESTAMP(6)", "TIMESTAMP WITH TIME ZONE"],
    "interval":  ["INTERVAL YEAR", "INTERVAL YEAR TO MONTH", "INTERVAL MONTH",
                  "INTERVAL DAY", "INTERVAL DAY TO HOUR",
                  "INTERVAL DAY TO MINUTE", "INTERVAL DAY TO SECOND",
                  "INTERVAL HOUR", "INTERVAL HOUR TO MINUTE",
                  "INTERVAL HOUR TO SECOND", "INTERVAL MINUTE",
                  "INTERVAL MINUTE TO SECOND", "INTERVAL SECOND"],
    "period":    ["PERIOD(DATE)", "PERIOD(TIMESTAMP(6))"],
    "complex":   ["JSON", "XML", "ST_GEOMETRY", "ARRAY", "BOOLEAN"],
}


# ───────────────────────────────────────────────────────────────────────
# Baseline schemas (Snapshot #1). Tables use a deliberately broad mix of
# Teradata types so the Metrics / Usage / Search pages don't look monotone.
# Column tuples: (name, data_type, nullable, ordinal_position)
# ───────────────────────────────────────────────────────────────────────
BASELINE_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "core_banking": {
        "description": "Core transactional banking data",
        "tables": {
            "customers": {
                "type": "TABLE",
                "columns": [
                    ("customer_id",      "INTEGER",        False,  1),
                    ("customer_uuid",    "CHAR(36)",       False,  2),
                    ("first_name",       "VARCHAR(100)",   False,  3),
                    ("last_name",        "VARCHAR(100)",   False,  4),
                    ("date_of_birth",    "DATE",           True,   5),
                    ("email",            "VARCHAR(255)",   True,   6),
                    ("phone",            "VARCHAR(50)",    True,   7),
                    ("customer_since",   "DATE",           False,  8),
                    ("risk_rating",      "VARCHAR(20)",    True,   9),
                    ("kyc_status",       "VARCHAR(20)",    False, 10),
                    ("country_code",     "CHAR(2)",        False, 11),
                    ("profile_json",     "JSON",           True,  12),
                    ("avatar_blob",      "BLOB",           True,  13),
                ],
            },
            "accounts": {
                "type": "TABLE",
                "columns": [
                    ("account_id",       "INTEGER",        False,  1),
                    ("customer_id",      "INTEGER",        False,  2),
                    ("account_type",     "VARCHAR(30)",    False,  3),
                    ("currency",         "CHAR(3)",        False,  4),
                    ("balance",          "DECIMAL(18,2)",  False,  5),
                    ("overdraft_limit",  "DECIMAL(18,2)",  True,   6),
                    ("opened_date",      "DATE",           False,  7),
                    ("status",           "VARCHAR(20)",    False,  8),
                    ("branch_id",        "INTEGER",        True,   9),
                    ("last_active_ts",   "TIMESTAMP(6)",   True,  10),
                    ("active_period",    "PERIOD(DATE)",   True,  11),
                ],
            },
            "transactions": {
                "type": "TABLE",
                "columns": [
                    ("transaction_id",    "BIGINT",                      False, 1),
                    ("account_id",        "INTEGER",                     False, 2),
                    ("transaction_ts",    "TIMESTAMP WITH TIME ZONE",    False, 3),
                    ("amount",            "DECIMAL(18,2)",               False, 4),
                    ("currency",          "CHAR(3)",                     False, 5),
                    ("transaction_type",  "VARCHAR(20)",                 False, 6),
                    ("description",      "VARCHAR(500)",                 True,  7),
                    ("counterparty_id",   "INTEGER",                     True,  8),
                    ("channel",           "VARCHAR(30)",                 True,  9),
                    ("geo_location",      "ST_GEOMETRY",                 True, 10),
                    ("raw_payload",       "CLOB",                        True, 11),
                    ("settlement_lag",    "INTERVAL DAY TO SECOND",      True, 12),
                ],
            },
            "loans": {
                "type": "TABLE",
                "columns": [
                    ("loan_id",             "INTEGER",         False,  1),
                    ("customer_id",         "INTEGER",         False,  2),
                    ("loan_type",           "VARCHAR(30)",     False,  3),
                    ("principal",           "DECIMAL(18,2)",   False,  4),
                    ("interest_rate",       "DECIMAL(5,4)",    False,  5),
                    ("start_date",          "DATE",            False,  6),
                    ("maturity_date",       "DATE",            False,  7),
                    ("term_months",         "SMALLINT",        False,  8),
                    ("outstanding_balance", "DECIMAL(18,2)",   False,  9),
                    ("collateral_value",    "DECIMAL(18,2)",   True,  10),
                    ("status",              "VARCHAR(20)",     False, 11),
                    ("tenor",               "INTERVAL YEAR TO MONTH", True, 12),
                ],
            },
            "branches": {
                "type": "TABLE",
                "columns": [
                    ("branch_id",     "INTEGER",       False, 1),
                    ("branch_code",   "CHAR(10)",      False, 2),
                    ("branch_name",   "VARCHAR(100)",  False, 3),
                    ("city",          "VARCHAR(100)",  False, 4),
                    ("country_code",  "CHAR(2)",       False, 5),
                    ("region",        "VARCHAR(50)",   True,  6),
                    ("opened_date",   "DATE",          False, 7),
                    ("geo_point",     "ST_GEOMETRY",   True,  8),
                ],
            },
            # ── Procedural objects (v1.10) ── These have no columns but
            # still produce graph nodes + edges so the System Graph page
            # shows every Teradata object type, not just tables/views.
            "sp_daily_close": {"type": "STORED_PROCEDURE", "columns": []},
            "fn_calc_interest": {"type": "FUNCTION", "columns": []},
            "trg_audit_transaction": {"type": "TRIGGER", "columns": []},
        },
    },
    "risk_management": {
        "description": "Risk, exposure and compliance",
        "tables": {
            "credit_scores": {
                "type": "TABLE",
                "columns": [
                    ("score_id",        "INTEGER",         False, 1),
                    ("customer_id",     "INTEGER",         False, 2),
                    ("score_date",      "DATE",            False, 3),
                    ("score_value",     "SMALLINT",        False, 4),
                    ("model_version",   "VARCHAR(20)",     False, 5),
                    ("risk_category",   "VARCHAR(30)",     False, 6),
                    ("model_features",  "JSON",            True,  7),
                ],
            },
            "exposure_summary": {
                "type": "VIEW",
                "columns": [
                    ("customer_id",        "INTEGER",        False, 1),
                    ("total_exposure",     "DECIMAL(18,2)",  False, 2),
                    ("secured_exposure",   "DECIMAL(18,2)",  False, 3),
                    ("unsecured_exposure", "DECIMAL(18,2)",  False, 4),
                    ("exposure_date",      "DATE",           False, 5),
                ],
            },
            "risk_events": {
                "type": "TABLE",
                "columns": [
                    ("event_id",       "BIGINT",          False, 1),
                    ("customer_id",    "INTEGER",         False, 2),
                    ("event_type",     "VARCHAR(50)",     False, 3),
                    ("event_ts",       "TIMESTAMP(6)",    False, 4),
                    ("severity",       "VARCHAR(20)",     False, 5),
                    ("description",    "LONG VARCHAR",    True,  6),
                    ("resolved",       "BOOLEAN",         False, 7),
                    ("supporting_doc", "XML",             True,  8),
                ],
            },
            "collateral_register": {
                "type": "TABLE",
                "columns": [
                    ("collateral_id",      "INTEGER",       False, 1),
                    ("loan_id",            "INTEGER",       False, 2),
                    ("collateral_type",    "VARCHAR(50)",   False, 3),
                    ("valuation_amount",   "DECIMAL(18,2)", False, 4),
                    ("valuation_date",     "DATE",          False, 5),
                    ("lien_position",      "BYTEINT",       True,  6),
                    ("appraisal_doc",      "BLOB",          True,  7),
                ],
            },
            "limits_matrix": {
                "type": "TABLE",
                "columns": [
                    ("limit_id",       "INTEGER",        False, 1),
                    ("customer_id",    "INTEGER",        False, 2),
                    ("product_code",   "CHAR(10)",       False, 3),
                    ("limit_amount",   "DECIMAL(20,6)",  False, 4),
                    ("effective_from", "DATE",           False, 5),
                    ("effective_to",   "DATE",           True,  6),
                    ("approved_by",    "VARCHAR(100)",   True,  7),
                ],
            },
            # ── Procedural objects (v1.10) ──
            "m_format_risk_alert": {"type": "MACRO", "columns": []},
        },
    },
    "reporting": {
        "description": "Regulatory and management reporting",
        "tables": {
            "regulatory_capital": {
                "type": "VIEW",
                "columns": [
                    ("report_date",        "DATE",          False, 1),
                    ("capital_tier",       "VARCHAR(20)",   False, 2),
                    ("amount",             "DECIMAL(18,2)", False, 3),
                    ("ratio",              "DECIMAL(8,4)",  False, 4),
                    ("regulatory_minimum", "DECIMAL(8,4)",  False, 5),
                ],
            },
            "daily_pl_summary": {
                "type": "VIEW",
                "columns": [
                    ("report_date",    "DATE",          False, 1),
                    ("business_line",  "VARCHAR(50)",   False, 2),
                    ("gross_revenue",  "DECIMAL(18,2)", False, 3),
                    ("net_revenue",    "DECIMAL(18,2)", False, 4),
                    ("cost_of_risk",   "DECIMAL(18,2)", False, 5),
                    ("fx_impact",      "DECIMAL(18,2)", True,  6),
                ],
            },
            "loan_portfolio_report": {
                "type": "VIEW",
                "columns": [
                    ("report_date",        "DATE",          False, 1),
                    ("loan_type",          "VARCHAR(30)",   False, 2),
                    ("total_outstanding",  "DECIMAL(20,2)", False, 3),
                    ("avg_interest_rate",  "DECIMAL(5,4)",  False, 4),
                    ("npl_ratio",          "DECIMAL(8,4)",  False, 5),
                    ("coverage_ratio",     "DECIMAL(8,4)",  False, 6),
                ],
            },
            "customer_360_view": {
                "type": "VIEW",
                "columns": [
                    ("customer_id",    "INTEGER",        False, 1),
                    ("full_name",      "VARCHAR(200)",   False, 2),
                    ("total_balance",  "DECIMAL(18,2)",  True,  3),
                    ("total_loans",    "DECIMAL(18,2)",  True,  4),
                    ("credit_score",   "SMALLINT",       True,  5),
                    ("risk_category",  "VARCHAR(30)",    True,  6),
                    ("segment",        "VARCHAR(50)",    True,  7),
                ],
            },
            # ── Procedural objects (v1.10) ──
            "sp_generate_regulatory_report": {"type": "STORED_PROCEDURE", "columns": []},
        },
    },
    "staging": {
        "description": "ETL staging area",
        "tables": {
            "stg_customer_feed": {
                "type": "TABLE",
                "columns": [
                    ("feed_id",        "BIGINT",       False, 1),
                    ("raw_data",       "CLOB",         False, 2),
                    ("load_timestamp", "TIMESTAMP(6)", False, 3),
                    ("source_system",  "VARCHAR(50)",  False, 4),
                    ("processed",      "BOOLEAN",      False, 5),
                ],
            },
            "stg_transaction_feed": {
                "type": "TABLE",
                "columns": [
                    ("feed_id",        "BIGINT",       False, 1),
                    ("raw_data",       "CLOB",         False, 2),
                    ("load_timestamp", "TIMESTAMP(6)", False, 3),
                    ("source_system",  "VARCHAR(50)",  False, 4),
                    ("batch_id",       "INTEGER",      True,  5),
                    ("checksum",       "BYTE(16)",     True,  6),
                ],
            },
        },
    },
}


# ───────────────────────────────────────────────────────────────────────
# Mutation timeline — 9 deltas producing snapshots 2..10. Each mutation
# tells a short story (rollout, widening, refactor, decommission) and
# triggers one or more change types so the Changes / Impact / Criticality
# pages light up across the whole timeline.
#
# Schema of each mutation dict:
#   add_schemas     : { schema_name: {description, tables: {...}} }
#   add_tables      : { schema_name: { table_name: {type, columns} } }
#   add_columns     : [ (schema, table, (name, dtype, nullable, ordpos)) ]
#   modify_types    : { (schema, table, col): new_dtype }
#   modify_nullable : { (schema, table, col): new_nullable_bool }
#   move_columns    : { (schema, table): { col_name: new_ordinal_position } }
#   type_changes    : { (schema, table): new_object_type }   # TABLE<->VIEW
#   remove_columns  : [ (schema, table, col) ]
#   remove_tables   : [ (schema, table) ]
#   remove_schemas  : [ schema_name ]
# ───────────────────────────────────────────────────────────────────────
MUTATIONS: List[Tuple[str, Dict[str, Any]]] = [

    # S2 — Analytics sandbox spins up (SCHEMA_ADDED + TABLE_ADDED)
    ("Analytics sandbox spun up for DS team", {
        "add_schemas": {
            "analytics_sandbox": {
                "description": "Ad-hoc experimentation by data science team",
                "tables": {
                    "experiment_runs": {
                        "type": "TABLE",
                        "columns": [
                            ("run_id",          "INTEGER",        False, 1),
                            ("experiment_name", "VARCHAR(100)",   False, 2),
                            ("started_ts",      "TIMESTAMP(6)",   False, 3),
                            ("finished_ts",     "TIMESTAMP(6)",   True,  4),
                            ("duration",        "INTERVAL HOUR TO SECOND", True, 5),
                            ("owner",           "VARCHAR(100)",   False, 6),
                            ("params_json",     "JSON",           True,  7),
                            ("notes",           "CLOB",           True,  8),
                        ],
                    },
                    "feature_store_mv": {
                        "type": "VIEW",
                        "columns": [
                            ("customer_id",     "INTEGER",        False, 1),
                            ("feature_vector",  "ARRAY",          True,  2),
                            ("computed_at",     "TIMESTAMP(6)",   False, 3),
                            ("version_tag",     "VARCHAR(20)",    False, 4),
                        ],
                    },
                },
            },
        },
    }),

    # S3 — New product attributes rolled in (COLUMN_ADDED)
    ("New product attributes added to loans and accounts", {
        "add_columns": [
            ("core_banking", "loans",      ("product_code",       "CHAR(10)",       True, 13)),
            ("core_banking", "loans",      ("origination_channel","VARCHAR(30)",    True, 14)),
            ("core_banking", "accounts",   ("iban",               "VARCHAR(34)",    True, 12)),
            ("core_banking", "accounts",   ("bic",                "VARCHAR(11)",    True, 13)),
            ("core_banking", "customers",  ("segment",            "VARCHAR(50)",    True, 14)),
            ("risk_management","credit_scores",("pd_12m",         "DECIMAL(8,6)",   True, 8)),
        ],
    }),

    # S4 — Monetary-field widening for 2026 capital adequacy rule
    # (COLUMN_TYPE_CHANGED)
    ("Monetary widening for capital adequacy rollout", {
        "modify_types": {
            ("core_banking", "loans",        "principal"):          "DECIMAL(22,2)",
            ("core_banking", "loans",        "outstanding_balance"):"DECIMAL(22,2)",
            ("core_banking", "transactions", "amount"):             "DECIMAL(22,2)",
            ("risk_management","collateral_register","valuation_amount"): "DECIMAL(22,2)",
            ("core_banking", "customers",    "email"):              "VARCHAR(320)",
            ("risk_management","credit_scores","score_value"):      "DECIMAL(6,2)",
        },
    }),

    # S5 — Nullability tightening/loosening
    # (COLUMN_NULLABILITY_CHANGED)
    ("Data-quality pass: tighten/loosen nullability", {
        "modify_nullable": {
            ("core_banking", "customers",   "email"):          False,   # was True
            ("core_banking", "customers",   "phone"):          False,   # was True
            ("core_banking", "transactions","amount"):         True,    # was False
            ("core_banking", "loans",       "collateral_value"): False, # was True
            ("risk_management","risk_events","supporting_doc"):False,   # was True
        },
    }),

    # S6 — Column reorder on transactions for query performance
    # (COLUMN_POSITION_CHANGED)
    ("Column reorder on transactions (PI optimisation)", {
        # Move currency up near amount, push description and counterparty back.
        "move_columns": {
            ("core_banking", "transactions"): {
                "transaction_id":   1,
                "account_id":       2,
                "transaction_ts":   3,
                "amount":           4,
                "currency":         5,
                "transaction_type": 6,
                "channel":          7,   # was 9
                "counterparty_id":  8,   # was 8 (unchanged)
                "description":      9,   # was 7
                "geo_location":     10,  # unchanged
                "raw_payload":      11,  # unchanged
                "settlement_lag":   12,  # unchanged
            },
        },
    }),

    # S7 — exposure_summary materialized (VIEW -> TABLE)
    # (TABLE_TYPE_CHANGED)
    ("Materialize exposure_summary for perf", {
        "type_changes": {
            ("risk_management", "exposure_summary"): "TABLE",
        },
    }),

    # S8 — Retire legacy staging feed (TABLE_REMOVED)
    ("Retire legacy stg_customer_feed (migrated to Kafka)", {
        "remove_tables": [
            ("staging", "stg_customer_feed"),
        ],
    }),

    # S9 — GDPR cleanup: drop PII-heavy columns (COLUMN_REMOVED)
    ("GDPR cleanup: drop PII-adjacent columns", {
        "remove_columns": [
            ("core_banking", "customers",    "avatar_blob"),
            ("core_banking", "customers",    "profile_json"),
            ("core_banking", "transactions", "raw_payload"),
            ("risk_management","risk_events","supporting_doc"),
        ],
    }),

    # S10 — Scrap the sandbox (SCHEMA_REMOVED)
    ("Decommission analytics_sandbox after DS migration", {
        "remove_schemas": ["analytics_sandbox"],
    }),
]


# ───────────────────────────────────────────────────────────────────────
# Mutation application — pure, deterministic. Takes a snapshot definition
# (dict-of-dicts) and returns a new one with the mutation applied.
# ───────────────────────────────────────────────────────────────────────
def apply_mutation(schemas: Dict[str, Any], mutation: Dict[str, Any]) -> Dict[str, Any]:
    """Return a deep-copied schemas dict with the mutation applied."""
    out = copy.deepcopy(schemas)

    # ADD schemas
    for name, definition in mutation.get("add_schemas", {}).items():
        out[name] = copy.deepcopy(definition)

    # ADD tables (into existing schemas)
    for schema_name, tables in mutation.get("add_tables", {}).items():
        out.setdefault(schema_name, {"description": "", "tables": {}})
        for tname, tinfo in tables.items():
            out[schema_name]["tables"][tname] = copy.deepcopy(tinfo)

    # ADD columns
    for schema_name, table_name, coldef in mutation.get("add_columns", []):
        out[schema_name]["tables"][table_name]["columns"].append(coldef)

    # MODIFY types
    for (schema_name, table_name, col_name), new_type in mutation.get("modify_types", {}).items():
        cols = out[schema_name]["tables"][table_name]["columns"]
        out[schema_name]["tables"][table_name]["columns"] = [
            (cn, new_type if cn == col_name else dt, nl, op)
            for (cn, dt, nl, op) in cols
        ]

    # MODIFY nullability
    for (schema_name, table_name, col_name), new_nl in mutation.get("modify_nullable", {}).items():
        cols = out[schema_name]["tables"][table_name]["columns"]
        out[schema_name]["tables"][table_name]["columns"] = [
            (cn, dt, new_nl if cn == col_name else nl, op)
            for (cn, dt, nl, op) in cols
        ]

    # MOVE columns (ordinal_position reassignment)
    for (schema_name, table_name), new_positions in mutation.get("move_columns", {}).items():
        cols = out[schema_name]["tables"][table_name]["columns"]
        out[schema_name]["tables"][table_name]["columns"] = [
            (cn, dt, nl, new_positions.get(cn, op))
            for (cn, dt, nl, op) in cols
        ]

    # TABLE_TYPE changes (TABLE <-> VIEW)
    for (schema_name, table_name), new_obj_type in mutation.get("type_changes", {}).items():
        out[schema_name]["tables"][table_name]["type"] = new_obj_type

    # REMOVE columns
    for schema_name, table_name, col_name in mutation.get("remove_columns", []):
        cols = out[schema_name]["tables"][table_name]["columns"]
        out[schema_name]["tables"][table_name]["columns"] = [
            (cn, dt, nl, op) for (cn, dt, nl, op) in cols if cn != col_name
        ]

    # REMOVE tables
    for schema_name, table_name in mutation.get("remove_tables", []):
        out[schema_name]["tables"].pop(table_name, None)

    # REMOVE schemas
    for schema_name in mutation.get("remove_schemas", []):
        out.pop(schema_name, None)

    return out


# ───────────────────────────────────────────────────────────────────────
# Persistence — one snapshot = N schemas × M tables × K columns.
# ───────────────────────────────────────────────────────────────────────
def persist_snapshot(
    session: Session,
    ts: datetime,
    description: str,
    is_baseline: bool,
    schemas: Dict[str, Any],
) -> int:
    """Insert one full snapshot and return its id."""
    snap = Snapshot(
        snapshot_time=ts,
        source_system="teradata_edw",
        description=description,
        is_baseline=is_baseline,
    )
    session.add(snap)
    session.flush()
    sid = snap.snapshot_id

    for schema_name, schema_info in schemas.items():
        ss = SchemaSnapshot(snapshot_id=sid, schema_name=schema_name)
        session.add(ss)
        session.flush()

        for table_name, table_info in schema_info["tables"].items():
            tbl = TableSnapshot(
                schema_id=ss.schema_id,
                table_name=table_name,
                object_type=table_info["type"],
            )
            session.add(tbl)
            session.flush()

            for col_name, dtype, nullable, ordpos in table_info["columns"]:
                session.add(ColumnSnapshot(
                    table_id=tbl.table_id,
                    column_name=col_name,
                    data_type=dtype,
                    nullable=nullable,
                    ordinal_position=ordpos,
                ))
    session.flush()
    return sid


# ───────────────────────────────────────────────────────────────────────
# Usage data — one record per distinct final-snapshot object. Numbers are
# roughly proportional to how load-bearing an object is in a real bank
# (customers/transactions/daily_pl very hot, sandbox cold).
# ───────────────────────────────────────────────────────────────────────
USAGE_ROWS: List[Dict[str, Any]] = [
    # core_banking
    {"object_name": "core_banking.customers",            "schema_name": "core_banking",     "object_type": "TABLE", "query_count": 18500, "user_count": 48},
    {"object_name": "core_banking.accounts",             "schema_name": "core_banking",     "object_type": "TABLE", "query_count": 14200, "user_count": 45},
    {"object_name": "core_banking.transactions",         "schema_name": "core_banking",     "object_type": "TABLE", "query_count": 31200, "user_count": 42},
    {"object_name": "core_banking.loans",                "schema_name": "core_banking",     "object_type": "TABLE", "query_count": 10800, "user_count": 27},
    {"object_name": "core_banking.branches",             "schema_name": "core_banking",     "object_type": "TABLE", "query_count": 3200,  "user_count": 15},
    # risk_management
    {"object_name": "risk_management.credit_scores",     "schema_name": "risk_management",  "object_type": "TABLE", "query_count": 9600,  "user_count": 22},
    {"object_name": "risk_management.exposure_summary",  "schema_name": "risk_management",  "object_type": "TABLE", "query_count": 7800,  "user_count": 20},
    {"object_name": "risk_management.risk_events",       "schema_name": "risk_management",  "object_type": "TABLE", "query_count": 4500,  "user_count": 14},
    {"object_name": "risk_management.collateral_register","schema_name":"risk_management",  "object_type": "TABLE", "query_count": 2200,  "user_count": 9},
    {"object_name": "risk_management.limits_matrix",     "schema_name": "risk_management",  "object_type": "TABLE", "query_count": 3400,  "user_count": 12},
    # reporting
    {"object_name": "reporting.regulatory_capital",      "schema_name": "reporting",        "object_type": "VIEW",  "query_count": 19200, "user_count": 58},
    {"object_name": "reporting.daily_pl_summary",        "schema_name": "reporting",        "object_type": "VIEW",  "query_count": 23400, "user_count": 62},
    {"object_name": "reporting.loan_portfolio_report",   "schema_name": "reporting",        "object_type": "VIEW",  "query_count": 14800, "user_count": 36},
    {"object_name": "reporting.customer_360_view",       "schema_name": "reporting",        "object_type": "VIEW",  "query_count": 20200, "user_count": 52},
    # staging
    {"object_name": "staging.stg_transaction_feed",      "schema_name": "staging",          "object_type": "TABLE", "query_count": 650,   "user_count": 4},
]


# ───────────────────────────────────────────────────────────────────────
# Explicit FEEDS edges (v1.10)
#
# The FK-heuristic in `graph_builder._build_graph_for_snapshot_in_session`
# creates edges from columns that end in `_id`, which gives us dim→fact
# relationships for free. But it can't see:
#   - views reading from multiple tables (no FK, just SELECT),
#   - procedural objects reading/writing data (no columns at all),
#   - staging→core flows where the staging side has no FK column.
#
# This list declares those edges explicitly in data-flow direction
# (producer → consumer). After `build_graph_for_snapshot()` creates
# the nodes for each snapshot, `_persist_explicit_edges()` resolves
# them against the snapshot's node_ids and inserts as FEEDS edges.
# Rows that reference an object not present in the snapshot (e.g.
# analytics_sandbox after S10) are silently skipped.
# ───────────────────────────────────────────────────────────────────────
EXPLICIT_FEEDS_EDGES: List[Tuple[str, str]] = [
    # ── Staging feeds the core ──
    ("staging.stg_customer_feed",            "core_banking.customers"),
    ("staging.stg_transaction_feed",         "core_banking.transactions"),

    # ── Risk summaries consume core + collateral ──
    ("core_banking.loans",                   "risk_management.exposure_summary"),
    ("risk_management.collateral_register",  "risk_management.exposure_summary"),

    # ── Reporting views consume core + risk ──
    ("core_banking.transactions",            "reporting.daily_pl_summary"),
    ("core_banking.accounts",                "reporting.daily_pl_summary"),
    ("core_banking.loans",                   "reporting.loan_portfolio_report"),
    ("core_banking.customers",               "reporting.customer_360_view"),
    ("core_banking.accounts",                "reporting.customer_360_view"),
    ("core_banking.loans",                   "reporting.customer_360_view"),
    ("risk_management.credit_scores",        "reporting.customer_360_view"),
    ("risk_management.exposure_summary",     "reporting.regulatory_capital"),
    ("core_banking.loans",                   "reporting.regulatory_capital"),

    # ── Procedural objects: stored_procs/triggers/functions/macros ──
    # sp_daily_close reads transactions + accounts, writes daily_pl_summary
    ("core_banking.transactions",            "core_banking.sp_daily_close"),
    ("core_banking.accounts",                "core_banking.sp_daily_close"),
    ("core_banking.sp_daily_close",          "reporting.daily_pl_summary"),
    # fn_calc_interest: reads loans (scalar fn used in views/procs)
    ("core_banking.loans",                   "core_banking.fn_calc_interest"),
    # trg_audit_transaction fires on transactions (no output table modelled)
    ("core_banking.transactions",            "core_banking.trg_audit_transaction"),
    # m_format_risk_alert: reads risk_events, used downstream by ops views
    ("risk_management.risk_events",          "risk_management.m_format_risk_alert"),
    # sp_generate_regulatory_report: reads regulatory_capital, writes out
    ("reporting.regulatory_capital",         "reporting.sp_generate_regulatory_report"),
]


def _persist_explicit_edges(snapshot_id: int) -> int:
    """Materialise EXPLICIT_FEEDS_EDGES for one snapshot.

    Resolves each `(source_name, target_name)` tuple against the graph_nodes
    already persisted for this snapshot and inserts a FEEDS edge when BOTH
    endpoints exist. Missing endpoints are skipped silently — this is what
    happens naturally after mutations drop an object (e.g. analytics_sandbox
    after S10); the edges simply stop rendering.
    Returns the number of edges persisted.
    """
    from app.graph.graph_models import GraphNode, GraphEdge
    from sqlalchemy import select as _select
    from sqlalchemy.orm import Session as _Session

    persisted = 0
    with _Session(engine) as session:
        with session.begin():
            # Build name→(node_id, node_uid) lookup for this snapshot.
            # Must live INSIDE session.begin() because issuing any execute()
            # auto-starts a transaction otherwise, and session.begin() then
            # raises "transaction is already begun".
            rows = session.execute(
                _select(GraphNode.node_id, GraphNode.object_name, GraphNode.node_uid)
                .where(GraphNode.snapshot_id == snapshot_id)
            ).all()
            by_name = {name: (nid, uid) for nid, name, uid in rows}

            for source_name, target_name in EXPLICIT_FEEDS_EDGES:
                src = by_name.get(source_name)
                tgt = by_name.get(target_name)
                if not src or not tgt:
                    continue  # an endpoint doesn't exist in this snapshot
                src_id, src_uid = src
                tgt_id, tgt_uid = tgt

                # Idempotent: don't duplicate if already there (the FK
                # heuristic might have created the same edge; we want
                # one edge per (source, target, type, snapshot)).
                already = session.execute(
                    _select(GraphEdge.edge_id)
                    .where(
                        GraphEdge.source_node_id == src_id,
                        GraphEdge.target_node_id == tgt_id,
                        GraphEdge.relationship_type == "FEEDS",
                        GraphEdge.snapshot_id == snapshot_id,
                    )
                ).first()
                if already:
                    continue

                session.add(GraphEdge(
                    source_node_id=src_id,
                    target_node_id=tgt_id,
                    relationship_type="FEEDS",
                    snapshot_id=snapshot_id,
                    from_node_uid=src_uid or "",
                    to_node_uid=tgt_uid or "",
                    edge_type="FEEDS",
                ))
                persisted += 1
    return persisted


# ───────────────────────────────────────────────────────────────────────
def wipe_demo_data() -> None:
    """DELETE all rows from demo + parser tables in FK-safe order.

    We don't drop the DB file so the backend process can stay attached.
    Order matters because of FKs (impacts → changes → snapshots, etc.).
    """
    print("[rich_seed] Wiping previous data (FK-safe)...")
    with Session(engine) as session:
        with session.begin():
            for table in [
                "object_criticality",
                "usage_event",
                "impact_event",
                "reasoning_event",
                "change_event",
                "attribute_lineage",
                "step",
                "process",
                "graph_edge",
                "graph_node",
                "column_snapshot",
                "table_snapshot",
                "schema_snapshot",
                "snapshot",
            ]:
                session.execute(text(f"DELETE FROM {table}"))


# ───────────────────────────────────────────────────────────────────────
def main() -> None:
    print("[rich_seed] Starting rich demo seed (v1.06 — sabroso edition)...")

    wipe_demo_data()

    # ──── 1. Build the 10 snapshot definitions (baseline + 9 mutations) ────
    defs: List[Dict[str, Any]] = [copy.deepcopy(BASELINE_SCHEMAS)]
    stories: List[str] = ["Baseline — banking EDW reference state"]
    current = BASELINE_SCHEMAS
    for story, mut in MUTATIONS:
        current = apply_mutation(current, mut)
        defs.append(current)
        stories.append(story)
    assert len(defs) == 10

    # Space snapshots across the last 30 days so the timeline page shows
    # a real chronological spread. Oldest → newest, 3-day cadence roughly.
    now = datetime.now(timezone.utc)
    snapshot_times = [now - timedelta(days=(9 - i) * 3 + 1) for i in range(10)]
    # Force the latest one to "now" so the UI shows a fresh state.
    snapshot_times[-1] = now

    # ──── 2. Persist all snapshots ────
    snapshot_ids: List[int] = []
    with Session(engine) as session:
        with session.begin():
            for i, (ts, story, schemas) in enumerate(zip(snapshot_times, stories, defs)):
                sid = persist_snapshot(
                    session, ts,
                    description=f"#{i+1} — {story}",
                    is_baseline=(i == 0),
                    schemas=schemas,
                )
                snapshot_ids.append(sid)
                print(f"[rich_seed] Snapshot {sid}: {story}")

    # ──── 3. Structural hash + object count per snapshot ────
    for sid in snapshot_ids:
        sha = compute_structural_hash(sid)
        metrics = compute_snapshot_metrics(sid)
        with Session(engine) as session:
            with session.begin():
                snap = session.get(Snapshot, sid)
                if snap:
                    snap.structural_hash = sha
                    snap.object_count = metrics.total_objects
        print(f"[rich_seed] Snapshot {sid}: hash={sha[:12]}…  objects={metrics.total_objects}")

    # ──── 4. Pairwise diffs (each consecutive pair tells one mutation story) ────
    diff_engine = DiffEngine()
    total_changes = 0
    change_type_counter: Dict[str, int] = {}
    for prev, curr in zip(snapshot_ids, snapshot_ids[1:]):
        changes = diff_engine.compute_diff(prev, curr)
        total_changes += len(changes)
        for c in changes:
            change_type_counter[c.change_type] = change_type_counter.get(c.change_type, 0) + 1
        print(f"[rich_seed] Diff {prev}->{curr}: {len(changes)} change(s)")

    # ──── 5. Graph build + node metrics for every snapshot ────
    # Order matters: (a) build_graph_for_snapshot creates nodes +
    # FK-heuristic FEEDS edges, (b) _persist_explicit_edges adds the
    # lineage we couldn't infer (views, procedural objects, staging),
    # (c) persist_node_metrics runs LAST so degree-based metrics see
    # the full edge set including explicit ones.
    total_explicit = 0
    for sid in snapshot_ids:
        build_graph_for_snapshot(sid)
        total_explicit += _persist_explicit_edges(sid)
        persist_node_metrics(sid)
    print(f"[rich_seed] Built graphs + metrics for {len(snapshot_ids)} snapshots "
          f"({total_explicit} explicit FEEDS edges added across all snapshots)")

    # ──── 6. Link diffs to graph + compute impact events ────
    # We do this for each consecutive pair so the Impact page has data
    # across the entire timeline, not just for the latest diff.
    total_impacts = 0
    for prev, curr in zip(snapshot_ids, snapshot_ids[1:]):
        mapping = link_changes_to_graph(curr)
        with Session(engine) as session:
            change_events = session.query(ChangeEvent).filter(
                ChangeEvent.snapshot_from == prev,
                ChangeEvent.snapshot_to == curr,
            ).all()
        for ce in change_events:
            node_id = mapping.get(ce.change_id)
            if node_id is None:
                continue
            downstream = compute_downstream_impact(node_id, curr, max_depth=5)
            upstream = compute_upstream_impact(node_id, curr, max_depth=5)
            impacts = downstream + upstream
            if impacts:
                persist_impact_events(
                    change_id=ce.change_id,
                    snapshot_id=curr,
                    impacts=impacts,
                )
                total_impacts += len(impacts)
    print(f"[rich_seed] Persisted {total_impacts} impact event(s) across all diffs")

    # ──── 7. Usage data + criticality ────
    # Usage rows are global (not per-snapshot). Criticality uses the latest
    # snapshot since that's the "current" state of the warehouse.
    tagged_usage = [dict(r, source="teradata_query_log") for r in USAGE_ROWS]
    ingested = ingest_usage_json(tagged_usage)
    print(f"[rich_seed] Usage records ingested: {ingested}")

    latest_sid = snapshot_ids[-1]
    crit_results = compute_criticality(latest_sid)
    high = sum(1 for r in crit_results if r["criticality_level"] == "HIGH")
    med  = sum(1 for r in crit_results if r["criticality_level"] == "MEDIUM")
    low  = sum(1 for r in crit_results if r["criticality_level"] == "LOW")
    print(f"[rich_seed] Criticality (snapshot {latest_sid}): {high} HIGH, {med} MED, {low} LOW")

    # ──── 8. Summary ────
    print("\n" + "=" * 68)
    print(" RICH SEED COMPLETE  —  10 snapshots, all change types covered")
    print("=" * 68)
    print(f" Snapshot IDs        : {snapshot_ids}")
    print(f" Total diffs         : {len(snapshot_ids) - 1}")
    print(f" Total changes       : {total_changes}")
    print(f" Total impacts       : {total_impacts}")
    print(f" Change-type breakdown:")
    for ct in sorted(change_type_counter):
        print(f"   {ct:28s} {change_type_counter[ct]}")
    print(f" Latest snapshot     : #{latest_sid}")
    print("=" * 68)
    print("\n UI is ready at http://localhost:3000")


if __name__ == "__main__":
    main()
