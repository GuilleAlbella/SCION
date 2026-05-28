"""Unit tests for the PDCR persisters (Pipeline 3, PR-C).

Covers the three public surfaces in ``app.usage.pdcr_persister``:

  - ``persist_dbql_log`` — reassembly, metadata fidelity, idempotency
  - ``persist_object_usage`` — type mapping, orphan handling, CI resolve
  - ``build_node_index`` — case-insensitive (schema, name) → node_id

Each test uses an in-memory SQLite DB with the full SCION schema
applied via ``Base.metadata.create_all`` so the unique constraint
on ``DBQLQuery(query_id, collect_timestamp)`` is real and the orphan
filter has actual ``graph_node`` rows to match against.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.graph.graph_models import GraphNode
from app.metadata.pdcr_flat_file_reader import DBQLRecord, ObjectUsageRecord
from app.usage.dbql_models import DBQLQuery
from app.usage.pdcr_persister import (
    build_node_index,
    persist_dbql_log,
    persist_object_usage,
)
from app.usage.usage_models import UsageEvent


# ──── Test scaffolding ────

@pytest.fixture
def session():
    """Fresh in-memory DB with the full schema. One per test."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _dbql(
    query_id: int = 100,
    sql_row_no: int = 1,
    collect_ts: str = "2026-05-12 00:06:43.123456",
    sql: str = "SELECT 1",
    default_db: str = "TEDW",
    log_date: str = "2026/05/12",
) -> DBQLRecord:
    """Construct a DBQLRecord with sensible defaults."""
    return DBQLRecord(
        platform_name="Transcend-DevTest",
        log_date=log_date,
        proc_id=30692,
        collect_timestamp=collect_ts,
        query_id=query_id,
        sql_row_no=sql_row_no,
        sql_text_info=sql,
        default_database=default_db,
        qb_job_name=None,
        qb_proc_name=None,
    )


def _obj_usage(
    database: str = "TEDW",
    table: str = "customer",
    column: str = "id",
    object_type: str = "Col",
    count_a: int = 5,
    count_b: int = 2,
    access_ts: str = "2026-05-12 17:47:57.646670",
) -> ObjectUsageRecord:
    return ObjectUsageRecord(
        platform_name="Transcend-DevTest",
        database_name=database,
        table_name=table,
        column_name=column,
        data_size="1,000",
        object_type=object_type,
        count_a=count_a,
        count_b=count_b,
        count_c=None,
        count_d=1,
        count_e=1,
        access_timestamp=access_ts,
    )


# ──── persist_dbql_log: happy path ────

def test_persist_dbql_single_query_single_fragment(session):
    """One query, one fragment → one DBQLQuery row with the right
    fields. Smoke test for the whole reassembly+persist path."""
    result = persist_dbql_log([_dbql()], session)
    session.commit()

    assert result.inserted == 1
    rows = session.execute(select(DBQLQuery)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.query_id == 100
    assert row.sql_text == "SELECT 1"
    assert row.default_database == "TEDW"
    assert row.platform_name == "Transcend-DevTest"
    assert row.proc_id == 30692


def test_persist_dbql_reassembles_multi_fragment_query(session):
    """Three fragments out of row_no order → one DBQLQuery whose
    sql_text is the in-order concatenation. This is the byte-fidelity
    contract DataDNA correlation depends on."""
    fragments = [
        _dbql(query_id=42, sql_row_no=2, sql=" FROM users"),
        _dbql(query_id=42, sql_row_no=1, sql="SELECT id"),
        _dbql(query_id=42, sql_row_no=3, sql=" WHERE active = 1"),
    ]
    persist_dbql_log(fragments, session)
    session.commit()

    rows = session.execute(select(DBQLQuery)).scalars().all()
    assert len(rows) == 1
    assert rows[0].sql_text == "SELECT id FROM users WHERE active = 1"


def test_persist_dbql_multiple_distinct_queries(session):
    """Three different query_ids → three rows, each independent."""
    records = [
        _dbql(query_id=1, sql="SELECT 1"),
        _dbql(query_id=2, sql="SELECT 2"),
        _dbql(query_id=3, sql="SELECT 3"),
    ]
    result = persist_dbql_log(records, session)
    session.commit()

    assert result.inserted == 3
    rows = session.execute(select(DBQLQuery).order_by(DBQLQuery.query_id)).scalars().all()
    assert [r.query_id for r in rows] == [1, 2, 3]
    assert [r.sql_text for r in rows] == ["SELECT 1", "SELECT 2", "SELECT 3"]


# ──── persist_dbql_log: idempotency ────

def test_persist_dbql_is_idempotent_on_repeat(session):
    """Re-running the persister on the same input must NOT create
    duplicate rows — the natural key (query_id, collect_timestamp)
    catches it and increments ``skipped_duplicate``."""
    rec = _dbql(query_id=999)

    r1 = persist_dbql_log([rec], session)
    session.commit()
    assert r1.inserted == 1
    assert r1.skipped_duplicate == 0

    # Second run, same data
    r2 = persist_dbql_log([rec], session)
    session.commit()
    assert r2.inserted == 0
    assert r2.skipped_duplicate == 1

    # Only one row in the table
    assert session.execute(select(DBQLQuery).where(DBQLQuery.query_id == 999)).scalars().all().__len__() == 1


def test_persist_dbql_same_query_id_different_timestamp_not_duplicate(session):
    """Teradata can reuse QueryID across procid rollovers; if the
    collect_timestamp differs the persister must treat them as
    distinct queries.

    Note: within a *single* persist call, records sharing a query_id
    are treated as fragments of the same query (that's what the
    reassembly contract says). The "two distinct queries at the same
    QueryID" scenario happens across batches — typically two separate
    PDCR extract windows. Simulate it here with two calls.
    """
    a = _dbql(query_id=777, collect_ts="2026-05-12 00:00:00.000000")
    b = _dbql(query_id=777, collect_ts="2026-05-12 12:00:00.000000")

    persist_dbql_log([a], session)
    session.commit()
    persist_dbql_log([b], session)
    session.commit()

    rows = session.execute(
        select(DBQLQuery).where(DBQLQuery.query_id == 777)
    ).scalars().all()
    assert len(rows) == 2


def test_persist_dbql_skips_null_query_id_records(session):
    """Records with query_id=None can't be persisted and shouldn't
    crash the batch. They land in ``skipped_invalid``."""
    valid = _dbql(query_id=1)
    invalid = DBQLRecord(
        platform_name="P", log_date="2026/05/12", proc_id=1,
        collect_timestamp="2026-05-12 00:00:00", query_id=None,
        sql_row_no=1, sql_text_info="orphan", default_database=None,
        qb_job_name=None, qb_proc_name=None,
    )
    result = persist_dbql_log([valid, invalid], session)
    session.commit()
    assert result.inserted == 1
    assert result.skipped_invalid == 1


def test_persist_dbql_skips_invalid_timestamp(session):
    """Empty/unparseable collect_timestamp → skipped_invalid, no
    crash."""
    invalid = _dbql(query_id=42, collect_ts="")
    result = persist_dbql_log([invalid], session)
    session.commit()
    assert result.inserted == 0
    assert result.skipped_invalid == 1


# ──── persist_object_usage: happy path ────

def test_persist_object_usage_column_row(session):
    """A column-level usage row lands with the column name as
    object_name and COLUMN as object_type."""
    persist_object_usage([_obj_usage(object_type="Col")], session)
    session.commit()

    rows = session.execute(select(UsageEvent)).scalars().all()
    assert len(rows) == 1
    assert rows[0].object_type == "COLUMN"
    assert rows[0].object_name == "id"          # column
    assert rows[0].schema_name == "TEDW"
    assert rows[0].source == "pdcr"
    assert rows[0].query_count == 5            # count_a
    assert rows[0].user_count == 2             # count_b


def test_persist_object_usage_table_row(session):
    """A table-level row uses the table name as object_name."""
    persist_object_usage([_obj_usage(object_type="Tab")], session)
    session.commit()

    rows = session.execute(select(UsageEvent)).scalars().all()
    assert len(rows) == 1
    assert rows[0].object_type == "TABLE"
    assert rows[0].object_name == "customer"   # table, not column


def test_persist_object_usage_stashes_raw_counters(session):
    """All 5 raw PDCR counters land in source_json so the persister
    can be revisited once Rahul confirms the semantics."""
    rec = _obj_usage(count_a=10, count_b=20)
    rec = ObjectUsageRecord(
        **{**rec.__dict__, "count_c": 30, "count_d": 40, "count_e": 50}
    )
    persist_object_usage([rec], session)
    session.commit()

    row = session.execute(select(UsageEvent)).scalars().one()
    assert row.source_json["count_a"] == 10
    assert row.source_json["count_b"] == 20
    assert row.source_json["count_c"] == 30
    assert row.source_json["count_d"] == 40
    assert row.source_json["count_e"] == 50
    assert row.source_json["object_type_pdcr"] == "Col"


# ──── persist_object_usage: unmapped type skipping ────

def test_persist_object_usage_skips_unmapped_types(session):
    """The 14 PDCR types we don't model yet (UDF, SP, Tmp, etc.)
    must be skipped silently with a per-type counter, not crash."""
    records = [
        _obj_usage(object_type="UDF"),
        _obj_usage(object_type="UDF"),
        _obj_usage(object_type="SP"),
        _obj_usage(object_type="Col"),   # this one should land
    ]
    result = persist_object_usage(records, session)
    session.commit()

    assert result.inserted == 1
    assert result.skipped_unmapped_type == 3
    assert result.skipped_by_type == {"UDF": 2, "SP": 1}


# ──── persist_object_usage: case-insensitive resolve ────

def test_persist_object_usage_resolves_case_insensitively(session):
    """The PDCR file uses UPPERCASE; the dict uses original case.
    With ``snapshot_id`` provided, the persister must accept PDCR
    rows whose identifiers match graph_node case-insensitively."""
    # Seed the graph with mixed-case identifier (as it would appear
    # after a dict-import).
    session.add(
        GraphNode(
            object_type="TABLE",
            object_name="Customer_Orders",   # mixed case from CREATE TABLE
            snapshot_id=1,
            schema_name="MyDb",
            node_uid="MyDb.Customer_Orders",
        )
    )
    session.flush()

    # PDCR record arrives in UPPERCASE.
    rec = _obj_usage(
        database="MYDB",
        table="CUSTOMER_ORDERS",
        column="",
        object_type="Tab",
    )
    result = persist_object_usage([rec], session, snapshot_id=1)
    session.commit()

    assert result.inserted == 1
    assert result.skipped_orphan == 0


def test_persist_object_usage_skips_orphan_when_snapshot_provided(session):
    """When the PDCR identifier doesn't match any graph_node in the
    snapshot we count it as orphan and skip. The default behaviour
    of v1.21.6 — Rahul's PDCR window often pre-dates the dict
    extract."""
    # Empty graph: nothing to resolve against.
    rec = _obj_usage(database="MissingDB", table="MissingTable", object_type="Tab")
    result = persist_object_usage([rec], session, snapshot_id=1)
    session.commit()

    assert result.inserted == 0
    assert result.skipped_orphan == 1


def test_persist_object_usage_no_snapshot_accepts_all(session):
    """When ``snapshot_id`` is None the persister skips the orphan
    filter entirely — useful when usage data arrives before any
    dict has been ingested."""
    rec = _obj_usage(database="NoMatch", table="NoMatch", object_type="Tab")
    result = persist_object_usage([rec], session, snapshot_id=None)
    session.commit()
    assert result.inserted == 1
    assert result.skipped_orphan == 0


# ──── build_node_index ────

def test_build_node_index_lowercases_keys(session):
    """The map is keyed by ``(lower(schema_name), lower(object_name))``."""
    session.add_all([
        GraphNode(
            object_type="TABLE",
            object_name="Customers",
            snapshot_id=1,
            schema_name="MyDb",
            node_uid="MyDb.Customers",
        ),
        GraphNode(
            object_type="TABLE",
            object_name="Orders",
            snapshot_id=1,
            schema_name="OtherDb",
            node_uid="OtherDb.Orders",
        ),
    ])
    session.flush()

    idx = build_node_index(1, session)
    assert ("mydb", "customers") in idx
    assert ("otherdb", "orders") in idx
    # Keys should NOT be present in original case.
    assert ("MyDb", "Customers") not in idx


def test_build_node_index_isolates_snapshots(session):
    """Nodes in other snapshots must not leak into this snapshot's
    index — every PDCR resolve is scoped to one snapshot."""
    session.add_all([
        GraphNode(
            object_type="TABLE", object_name="t1", snapshot_id=1,
            schema_name="s", node_uid="s.t1",
        ),
        GraphNode(
            object_type="TABLE", object_name="t2", snapshot_id=2,
            schema_name="s", node_uid="s.t2",
        ),
    ])
    session.flush()

    idx_1 = build_node_index(1, session)
    idx_2 = build_node_index(2, session)
    assert ("s", "t1") in idx_1 and ("s", "t2") not in idx_1
    assert ("s", "t2") in idx_2 and ("s", "t1") not in idx_2


def test_build_node_index_empty_snapshot(session):
    """Snapshot with no graph_node rows yields an empty dict, not
    None or an exception."""
    idx = build_node_index(99, session)
    assert idx == {}
