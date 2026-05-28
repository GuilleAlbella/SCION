"""Edge-case tests for `format_detector`.

The detector is the single point of failure between "user uploads
files" and "ingest pipeline runs": misclassification routes a file to
the wrong reader and crashes downstream with a confusing parse error.
We pin every classification path here so a regression surfaces with a
clear "format detector misbehaved" rather than a stack trace 3 layers
deeper.

Coverage targets:
  - Empty / whitespace-only input → UNKNOWN, low confidence
  - JSON with BOM / leading whitespace → JSON detected
  - JSON with unrecognised shape → JSON / UNKNOWN content type
  - Flat-file with filename hint → high confidence
  - Flat-file without filename → medium / low confidence by arity
  - Garbage bytes → UNKNOWN
  - Mismatched filename vs content (filename says tables, content has 9
    fields = tabletext shape) → trust filename (high confidence) since
    extension drift is a known pattern
"""

from __future__ import annotations

import pytest

from app.metadata.format_detector import detect, Format, ContentType


# ──── Empty / blank ────

def test_empty_bytes_returns_unknown():
    """Empty file: nothing to classify."""
    r = detect(b"", filename="anything.dat")
    assert r.format is Format.UNKNOWN
    assert r.content_type is ContentType.UNKNOWN
    assert r.confidence == "low"


def test_only_whitespace_returns_unknown():
    """A file of just spaces/tabs/newlines has no signal."""
    r = detect(b"   \n\t\r\n  ", filename="x.dat")
    assert r.format is Format.UNKNOWN


# ──── JSON branches ────

def test_json_object_with_lineage_is_parser():
    """JSON starting with `{` and containing `objects` key → parser pipeline."""
    r = detect(b'{"objects": [], "lineage": []}', filename="lineage.json")
    assert r.format is Format.JSON
    assert r.content_type is ContentType.PARSER_LINEAGE
    assert r.confidence == "high"


def test_json_array_with_lineage_is_parser():
    """Top-level JSON array is also valid — parser exporters sometimes
    wrap output in an array. Detection should not break on shape variants."""
    r = detect(b'[{"objects": [{"x":1}]}]', filename="lineage.json")
    assert r.format is Format.JSON
    assert r.content_type is ContentType.PARSER_LINEAGE


def test_json_with_utf8_bom_still_detected():
    """Some Windows tools save JSON with a UTF-8 BOM; we strip it before
    looking at the first byte."""
    r = detect(b"\xef\xbb\xbf" + b'{"objects": []}', filename="lineage.json")
    assert r.format is Format.JSON
    assert r.content_type is ContentType.PARSER_LINEAGE


def test_json_with_leading_whitespace_still_detected():
    """Pretty-printers and IDEs sometimes prepend a blank line. Skip it."""
    r = detect(b'\n\n   {"objects": []}', filename="lineage.json")
    assert r.format is Format.JSON


def test_json_unknown_shape_returns_unknown_content_type():
    """JSON yes, but doesn't match any SCION schema → flag as UNKNOWN
    content type so the route handler can give a clear error to the
    user instead of trying to parse it as parser output."""
    r = detect(b'{"hello": "world"}', filename="random.json")
    assert r.format is Format.JSON
    assert r.content_type is ContentType.UNKNOWN
    assert r.confidence == "low"


# ──── Flat-file branches ────

# Minimal §-delimited row: 4 tech fields + 12 view fields = 16 total.
# Building it programmatically (not as a literal) so it's clear how the
# arity is constructed and easy to perturb in a single test.
def _flat_row(tech_count: int = 4, view_count: int = 12) -> bytes:
    fields = (
        ["TestSrc", "RUN_ID_001", "2026-04-29 10:00:00", "2026-04-29"][:tech_count]
        + [f"v{i}" for i in range(view_count)]
    )
    return ("§".join(fields) + "\r\n").encode("utf-8")


def test_flat_file_with_known_filename_high_confidence():
    """Filename matching Rahul's templates is the strongest signal we
    have — it should always win when present."""
    row = _flat_row()
    r = detect(row, filename="tablesv_full_export.rendered.dat")
    assert r.format is Format.FLAT_FILE
    assert r.content_type is ContentType.DICT_TABLES
    assert r.confidence == "high"


def test_flat_file_each_view_filename_routes_correctly():
    """All 8 known content types should map from their filename prefix.

    Six dictionary views + two PDCR usage extracts (Pipeline 3,
    added v1.21.6). PDCR filenames carry a timestamp window in the
    suffix (`pdcr_log_<from>_<to>.dat`) — the prefix is enough to
    identify the content type even without the dates.
    """
    cases = [
        ("databasesv_full_export.rendered.dat", ContentType.DICT_DATABASES),
        ("tablesv_full_export.rendered.dat", ContentType.DICT_TABLES),
        ("columnsv_full_export.rendered.dat", ContentType.DICT_COLUMNS),
        ("indicesv_full_export.rendered.dat", ContentType.DICT_INDICES),
        ("partitioningconstraintsv_full_export.rendered.dat", ContentType.DICT_PARTITIONING),
        ("tabletextv_full_export.rendered.dat", ContentType.DICT_TABLETEXT),
        ("pdcr_log_20260512_000000_to_20260513_000000.dat", ContentType.USAGE_DBQL),
        ("pdcr_object_usage_20260512_000000_to_20260513_000000.dat", ContentType.USAGE_OBJECT),
    ]
    row = _flat_row()
    for fname, expected in cases:
        r = detect(row, filename=fname)
        assert r.content_type is expected, f"{fname} routed to wrong type: {r.content_type}"
        assert r.confidence == "high", f"{fname} should be high confidence (filename match)"


def test_flat_file_filename_case_insensitive():
    """Customers rename files — `Tablesv_*.dat` should still match.
    The detector lowercases before comparing prefixes."""
    r = detect(_flat_row(), filename="Tablesv_FULL_export.rendered.dat")
    assert r.content_type is ContentType.DICT_TABLES
    assert r.confidence == "high"


def test_flat_file_no_filename_16_fields_returns_unknown():
    """Without a filename hint, 16 fields could be ANY of the 5
    standard views. We can't disambiguate so we flag UNKNOWN with
    a clear reason — caller should reject and ask for a proper name."""
    r = detect(_flat_row(), filename=None)
    assert r.format is Format.FLAT_FILE
    assert r.content_type is ContentType.UNKNOWN
    assert r.confidence == "low"
    assert "16-field" in r.reason or "filename" in r.reason


def test_flat_file_no_filename_9_fields_is_ambiguous():
    """9 fields used to uniquely mean tabletextv, but since v1.21.5
    partitioningconstraintsv also uses a 9-col + ENDREC layout (its
    constraint_text field can contain embedded newlines, same shape
    as tabletextv.RequestText). Without a filename hint we therefore
    can't disambiguate, and the detector returns UNKNOWN with a
    low-confidence reason that names both candidates so the operator
    knows what to do.
    """
    r = detect(_flat_row(view_count=5), filename=None)  # 4 tech + 5 = 9
    assert r.format is Format.FLAT_FILE
    assert r.content_type is ContentType.UNKNOWN
    assert r.confidence == "low"
    # The reason should mention both candidates so the operator can
    # re-upload with the original filename to disambiguate.
    assert "tabletext" in r.reason.lower()
    assert "partitioning" in r.reason.lower()


def test_flat_file_no_filename_10_fields_is_dbql():
    """10 fields is unique to pdcr_log (DBQL query log) among the
    known content types. The detector returns USAGE_DBQL with medium
    confidence even without a filename — there's only one candidate
    for arity 10, so it's safe to route. A filename would lift this
    to high confidence."""
    r = detect(_flat_row(view_count=6), filename=None)  # 4 tech + 6 = 10
    assert r.format is Format.FLAT_FILE
    assert r.content_type is ContentType.USAGE_DBQL
    assert r.confidence == "medium"
    assert "pdcr_log" in r.reason.lower() or "dbql" in r.reason.lower()


def test_flat_file_no_filename_12_fields_is_object_usage():
    """12 fields is unique to pdcr_object_usage. Same reasoning as
    the 10-field case — single candidate, medium confidence without
    filename, high with."""
    r = detect(_flat_row(view_count=8), filename=None)  # 4 tech + 8 = 12
    assert r.format is Format.FLAT_FILE
    assert r.content_type is ContentType.USAGE_OBJECT
    assert r.confidence == "medium"
    assert "object_usage" in r.reason.lower() or "object" in r.reason.lower()


def test_flat_file_unexpected_arity_returns_unknown():
    """Some other field count (8, 11, 13, 17, …) means layout drift or
    corruption: no known content type uses that arity, so we flag it
    loudly rather than guess. Note: 9, 10, 12, 16 are all valid arities
    today (covered by their own tests), so this test must pick a value
    outside that set.
    """
    r = detect(_flat_row(view_count=7), filename=None)  # 4 tech + 7 = 11
    assert r.format is Format.FLAT_FILE
    assert r.content_type is ContentType.UNKNOWN
    assert "unexpected" in r.reason.lower() or "drift" in r.reason.lower() or "review" in r.reason.lower()


def test_flat_file_pdcr_log_endrec_aware_arity_counting():
    """Regression: `pdcr_log` records have SQL text in field 7 that
    may contain embedded newlines. If the detector counts fields in
    the first *line* it sees 7 fields (truncated mid-record) and
    misroutes to UNKNOWN. With ENDREC-aware splitting it sees the
    full 10-field record and routes correctly.

    This is the exact bug that surfaced when Rahul shipped his first
    real `pdcr_log_*.dat` against SCION v1.21.5.
    """
    # Build a pdcr_log-shaped record: 10 §-separated fields, field 7
    # has an embedded newline (simulating multi-line SqlTextInfo), and
    # the record is terminated by `ENDREC`.
    sql_with_newline = "create multiset volatile table foo\n(col1 INTEGER)\nprimary index (col1)"
    fields = [
        "TestSrc", "2026/05/12", "12345",
        "2026-05-12 00:06:43.123456", "111222333", "1",
        sql_with_newline, "DEFAULT_DB", "", "",
    ]
    record = "§".join(fields) + "ENDREC\n"
    r = detect(record.encode("utf-8"), filename=None)
    assert r.format is Format.FLAT_FILE
    assert r.content_type is ContentType.USAGE_DBQL, (
        f"ENDREC-aware splitter should see 10 fields and route to USAGE_DBQL; "
        f"got {r.content_type} with reason: {r.reason}"
    )
    assert r.confidence == "medium"


def test_filename_wins_over_arity_when_both_disagree():
    """If a 16-field row has filename `tabletextv_*`, trust the
    filename — we'd rather mis-parse and surface a layout error
    later than silently route to the wrong reader."""
    r = detect(_flat_row(), filename="tabletextv_full_export.rendered.dat")
    assert r.content_type is ContentType.DICT_TABLETEXT
    assert r.confidence == "high"


# ──── Hard-fail garbage ────

def test_garbage_bytes_returns_unknown():
    """Random binary bytes that aren't JSON or flat-file — UNKNOWN."""
    r = detect(b"\x00\x01\x02\x03\x04\x05", filename="x")
    assert r.format is Format.UNKNOWN


def test_xml_returns_unknown():
    """XML is not in SCION's contract today; flag and let the user
    know rather than misroute as JSON."""
    r = detect(b"<?xml version='1.0'?><root/>", filename="x.xml")
    assert r.format is Format.UNKNOWN


def test_csv_returns_unknown():
    """Plain CSV (comma-delimited, no `§`) is not a supported format.
    We don't pretend it could be a flat-file."""
    r = detect(b"col1,col2,col3\nv1,v2,v3\n", filename="x.csv")
    assert r.format is Format.UNKNOWN
