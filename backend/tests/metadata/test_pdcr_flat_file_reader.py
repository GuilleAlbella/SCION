"""Unit tests for the PDCR flat-file readers (Pipeline 3, PR-B).

The two readers (`read_dbql_log` and `read_object_usage`) are the
narrow surface that turns Rahul's bytes into typed Python objects.
The persister (PR-C) and endpoint (PR-D) build on this contract, so
every shape variant a real file can produce is pinned here:

  - Happy path: well-formed records → expected dataclass values.
  - Multi-line SqlTextInfo in DBQL: must survive ENDREC splitting.
  - Escaped delimiters in any field: `\\§` collapses to literal `§`.
  - Wrong arity: raises PDCRFlatFileError with file:line context.
  - Empty file / trailing whitespace: yields zero records cleanly.
  - reassemble_query: groups + sorts + concatenates with byte
    fidelity (the SQL text Teradata emitted must come back exactly).
"""

from __future__ import annotations

import pytest

from app.metadata.pdcr_flat_file_reader import (
    DBQLRecord,
    ObjectUsageRecord,
    PDCRFlatFileError,
    iter_dbql_log,
    iter_object_usage,
    read_dbql_log,
    read_object_usage,
    reassemble_query,
)


# ──── Test fixtures ────
# Records are built as strings and written to a tmp_path file. We
# build them programmatically (not as multiline literals) so the
# arity is obvious and edits are local.

def _join_record(fields: list[str]) -> str:
    """Join fields with `§` and terminate with ENDREC + newline."""
    return "§".join(fields) + "ENDREC\n"


def _dbql_record(
    *,
    platform: str = "Transcend-DevTest",
    log_date: str = "2026/05/12",
    proc_id: str = "30692",
    collect_ts: str = "2026-05-12 00:06:43.623288",
    query_id: str = "306922306948954750",
    sql_row_no: str = "1",
    sql: str = "SELECT 1",
    default_db: str = "TEDW",
    qb_job: str = "",
    qb_proc: str = "",
) -> str:
    return _join_record([
        platform, log_date, proc_id, collect_ts, query_id,
        sql_row_no, sql, default_db, qb_job, qb_proc,
    ])


def _object_usage_record(
    *,
    platform: str = "Transcend-DevTest",
    database: str = "ADLTRD_GSS_Sizing",
    table: str = "STAGING_1778622599200",
    column: str = "MaxWISSDReadMBSecNode_SPDSK",
    data_size: str = "1,188",
    object_type: str = "Col",
    count_a: str = "1",
    count_b: str = "2",
    count_c: str = "",
    count_d: str = "1",
    count_e: str = "1",
    access_ts: str = "2026-05-12 17:47:57.646670",
) -> str:
    return _join_record([
        platform, database, table, column, data_size, object_type,
        count_a, count_b, count_c, count_d, count_e, access_ts,
    ])


# ──── DBQL: happy path ────

def test_read_dbql_single_record(tmp_path):
    """Smallest possible file: one well-formed record. Fields land
    on the expected dataclass attributes with correct types."""
    f = tmp_path / "pdcr_log_x.dat"
    f.write_text(_dbql_record(), encoding="utf-8")

    records = read_dbql_log(f)
    assert len(records) == 1

    r = records[0]
    assert r.platform_name == "Transcend-DevTest"
    assert r.log_date == "2026/05/12"
    assert r.proc_id == 30692
    assert r.collect_timestamp == "2026-05-12 00:06:43.623288"
    assert r.query_id == 306922306948954750
    assert r.sql_row_no == 1
    assert r.sql_text_info == "SELECT 1"
    assert r.default_database == "TEDW"
    assert r.qb_job_name is None        # empty string → None per _nn
    assert r.qb_proc_name is None


def test_read_dbql_multiple_records(tmp_path):
    """Multiple records concatenated correctly: ENDREC separates,
    each block parses independently."""
    f = tmp_path / "pdcr_log_multi.dat"
    payload = (
        _dbql_record(query_id="100", sql_row_no="1", sql="SELECT a") +
        _dbql_record(query_id="100", sql_row_no="2", sql=" FROM t") +
        _dbql_record(query_id="200", sql_row_no="1", sql="DROP TABLE x")
    )
    f.write_text(payload, encoding="utf-8")

    records = read_dbql_log(f)
    assert len(records) == 3
    assert records[0].query_id == 100 and records[0].sql_row_no == 1
    assert records[1].query_id == 100 and records[1].sql_row_no == 2
    assert records[2].query_id == 200 and records[2].sql_row_no == 1


def test_read_dbql_preserves_multiline_sql(tmp_path):
    """Critical regression test: SqlTextInfo can contain embedded
    newlines (real Teradata-formatted DDL spans multiple lines).
    The ENDREC splitter must keep the full text together; a naive
    line-based split would have broken the record mid-statement."""
    multiline_sql = (
        "create multiset volatile table batch_create_update_v\n"
        "(\n"
        "     start_di_created_ts TIMESTAMP(6),\n"
        "     table_name VARCHAR(50) CHARACTER SET UNICODE NOT CASESPECIFIC\n"
        ")\n"
        "primary index (table_name)\n"
        "ON COMMIT preserve rows;"
    )
    f = tmp_path / "pdcr_log_multiline.dat"
    f.write_text(_dbql_record(sql=multiline_sql), encoding="utf-8")

    records = read_dbql_log(f)
    assert len(records) == 1
    # Byte-identical to what we wrote — no characters dropped, no
    # boundary shenanigans. This is the property DataDNA correlation
    # depends on.
    assert records[0].sql_text_info == multiline_sql


def test_read_dbql_handles_escaped_delimiter_in_sql(tmp_path):
    """If a § appears inside the SQL itself (extremely rare but
    possible — e.g. CHR(167) literal), Rahul's exporter escapes it
    as `\\§`. The reader must collapse `\\§` back to literal `§`."""
    f = tmp_path / "pdcr_log_escaped.dat"
    # SELECT '§marker§' becomes SELECT '\§marker\§' on the wire.
    sql_with_escaped = "SELECT '\\§marker\\§' FROM x"
    f.write_text(_dbql_record(sql=sql_with_escaped), encoding="utf-8")

    records = read_dbql_log(f)
    assert len(records) == 1
    assert records[0].sql_text_info == "SELECT '§marker§' FROM x"


def test_read_dbql_thousand_separators_in_numeric(tmp_path):
    """BTEQ-formatted numeric fields can carry thousand separators
    (e.g. `378,910,604,592`). The `_parse_int` helper strips commas
    before parsing — same convention as the dict reader."""
    f = tmp_path / "pdcr_log_commas.dat"
    # 1,234,567 is a plausible large QueryID
    f.write_text(_dbql_record(query_id="1,234,567"), encoding="utf-8")

    records = read_dbql_log(f)
    assert records[0].query_id == 1234567


# ──── DBQL: error cases ────

def test_read_dbql_wrong_arity_raises(tmp_path):
    """9 fields instead of 10 → loud failure with file:line context
    and a sample of the offending bytes. This is FR-13 compliance:
    bad data surfaces as a clear error, not a silent partial parse."""
    f = tmp_path / "pdcr_log_bad.dat"
    # Build a record with only 9 fields.
    fields = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]
    f.write_text("§".join(fields) + "ENDREC\n", encoding="utf-8")

    with pytest.raises(PDCRFlatFileError) as excinfo:
        read_dbql_log(f)
    msg = str(excinfo.value)
    assert "expected 10 fields" in msg
    assert "got 9" in msg
    assert "pdcr_log_bad.dat" in msg
    assert "record#1" in msg


def test_read_dbql_empty_file_yields_zero_records(tmp_path):
    """Empty file: no records, no error. The endpoint above this
    decides whether to flag it ('uploaded empty file') — the reader
    just reports what it found."""
    f = tmp_path / "pdcr_log_empty.dat"
    f.write_text("", encoding="utf-8")
    assert read_dbql_log(f) == []


def test_iter_dbql_is_lazy(tmp_path):
    """The streaming variant must yield without loading the whole
    list. We can't easily test memory directly, but we can assert
    the function is a generator (lazy by Python contract)."""
    f = tmp_path / "pdcr_log_iter.dat"
    f.write_text(_dbql_record(), encoding="utf-8")

    gen = iter_dbql_log(f)
    # `gen` must be an iterator, not a list. Asserting on the type
    # is brittle; asserting on the protocol is robust.
    assert hasattr(gen, "__next__"), "iter_dbql_log must return an iterator"
    first = next(gen)
    assert isinstance(first, DBQLRecord)


# ──── Object Usage: happy path ────

def test_read_object_usage_single_record(tmp_path):
    """All 12 fields land in the right dataclass slots; numeric
    fields parse to int; empty string → None."""
    f = tmp_path / "pdcr_object_usage_x.dat"
    f.write_text(_object_usage_record(), encoding="utf-8")

    records = read_object_usage(f)
    assert len(records) == 1

    r = records[0]
    assert r.platform_name == "Transcend-DevTest"
    assert r.database_name == "ADLTRD_GSS_Sizing"
    assert r.table_name == "STAGING_1778622599200"
    assert r.column_name == "MaxWISSDReadMBSecNode_SPDSK"
    assert r.data_size == "1,188"   # kept raw — persister parses
    assert r.object_type == "Col"
    assert r.count_a == 1
    assert r.count_b == 2
    assert r.count_c is None        # empty → None
    assert r.count_d == 1
    assert r.count_e == 1
    assert r.access_timestamp == "2026-05-12 17:47:57.646670"


def test_read_object_usage_multiple_records(tmp_path):
    """Two records, different object types, both parsed correctly."""
    f = tmp_path / "pdcr_object_usage_multi.dat"
    payload = (
        _object_usage_record(object_type="Col", count_a="42") +
        _object_usage_record(object_type="Tbl", column="", count_a="7", count_b="3")
    )
    f.write_text(payload, encoding="utf-8")

    records = read_object_usage(f)
    assert len(records) == 2
    assert records[0].object_type == "Col"
    assert records[0].count_a == 42
    assert records[1].object_type == "Tbl"
    assert records[1].column_name == ""    # table-level rows have empty column
    assert records[1].count_a == 7


def test_read_object_usage_wrong_arity_raises(tmp_path):
    """Same FR-13 contract as DBQL: wrong field count → loud error."""
    f = tmp_path / "pdcr_object_usage_bad.dat"
    fields = ["A"] * 11        # one too few
    f.write_text("§".join(fields) + "ENDREC\n", encoding="utf-8")

    with pytest.raises(PDCRFlatFileError) as excinfo:
        read_object_usage(f)
    msg = str(excinfo.value)
    assert "expected 12 fields" in msg
    assert "got 11" in msg
    assert "record#1" in msg


# ──── reassemble_query ────

def test_reassemble_query_concatenates_in_row_no_order(tmp_path):
    """Two queries, three fragments total. Fragments come in
    deliberately out-of-order to verify the sort. Result must be
    byte-identical to "SqlRowNo 1 fragment" + "SqlRowNo 2 fragment"."""
    f = tmp_path / "pdcr_log_reassemble.dat"
    payload = (
        # Query 100 fragments out of order in the file:
        _dbql_record(query_id="100", sql_row_no="2", sql=" FROM users") +
        _dbql_record(query_id="100", sql_row_no="1", sql="SELECT id") +
        # Query 200, single fragment:
        _dbql_record(query_id="200", sql_row_no="1", sql="DROP TABLE x")
    )
    f.write_text(payload, encoding="utf-8")

    records = read_dbql_log(f)
    full = reassemble_query(records)

    assert full[100] == "SELECT id FROM users"
    assert full[200] == "DROP TABLE x"


def test_reassemble_query_handles_three_fragments(tmp_path):
    """A multi-fragment query whose third fragment finishes the
    statement. Tests that we handle more than 2 fragments correctly."""
    f = tmp_path / "pdcr_log_three_frags.dat"
    payload = (
        _dbql_record(query_id="999", sql_row_no="1", sql="SELECT ") +
        _dbql_record(query_id="999", sql_row_no="3", sql=" FROM t") +
        _dbql_record(query_id="999", sql_row_no="2", sql="a, b, c")
    )
    f.write_text(payload, encoding="utf-8")

    full = reassemble_query(read_dbql_log(f))
    assert full[999] == "SELECT a, b, c FROM t"


def test_reassemble_query_skips_null_query_ids():
    """A record with query_id=None should be filtered out, not
    crash the reassembly. Defensive — the contract says QueryID is
    always populated, but a partial extract could be missing it."""
    records = [
        DBQLRecord(
            platform_name="P", log_date="d", proc_id=1,
            collect_timestamp="t", query_id=None, sql_row_no=1,
            sql_text_info="orphan", default_database=None,
            qb_job_name=None, qb_proc_name=None,
        ),
        DBQLRecord(
            platform_name="P", log_date="d", proc_id=1,
            collect_timestamp="t", query_id=42, sql_row_no=1,
            sql_text_info="real", default_database=None,
            qb_job_name=None, qb_proc_name=None,
        ),
    ]
    full = reassemble_query(records)
    assert full == {42: "real"}
    assert None not in full
