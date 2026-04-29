"""Integration tests for the dict-import pipeline against Rahul's real sample.

Source: `Parser/Data extract 2/Sample 1/` — 6 files representing one full
extraction run from `Transcend-DevTest`. Locked to that exact sample so
any change in Rahul's contract surfaces here as a test failure rather
than corrupted snapshots in production.

If Rahul ships a v2 sample, copy it into a new fixtures folder and add a
parallel test — don't replace this one. The point is regression coverage
across format versions.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


# ──── Fixture path ────
# Tests run from anywhere, so resolve the sample relative to the repo
# root (3 levels up from this file: tests/metadata → tests → backend → root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SAMPLE_DIR = _REPO_ROOT / "Parser" / "Data extract 2" / "Sample 1"

# The 6 file names in Rahul's sample. If any one of them moves we want
# the test to fail with a clear "missing file" message, not a confusing
# "0 records parsed" downstream.
_SAMPLE_FILES = {
    "databases":    "databasesv_full_export.rendered.dat",
    "tables":       "tablesv_full_export.rendered.dat",
    "columns":      "columnsv_full_export.rendered.dat",
    "indices":      "indicesv_full_export.rendered.dat",
    "partitioning": "partitioningconstraintsv_full_export.rendered.dat",
    "tabletext":    "tabletextv_full_export.rendered.dat",
}


# Skip the whole module if the sample isn't present (e.g. CI without the
# Parser folder mounted). Keeps the suite green on minimal checkouts.
pytestmark = pytest.mark.skipif(
    not _SAMPLE_DIR.exists(),
    reason=f"Sample dir not found: {_SAMPLE_DIR}",
)


# ──── Reader-level smoke tests ────

def test_each_reader_parses_10_records():
    """Every file in Sample 1/ has exactly 10 records — anchor for the
    end-to-end count below. If Rahul resamples, update both numbers
    together."""
    from app.metadata import dict_flat_file_reader as r
    funcs = {
        "databases":    r.read_databases,
        "tables":       r.read_tables,
        "columns":      r.read_columns,
        "indices":      r.read_indices,
        "partitioning": r.read_partitioning,
        "tabletext":    r.read_tabletext,
    }
    for category, fn in funcs.items():
        path = _SAMPLE_DIR / _SAMPLE_FILES[category]
        records = fn(path)
        assert len(records) == 10, (
            f"{category}: expected 10 records, got {len(records)}"
        )


def test_format_detector_classifies_all_six_with_high_confidence():
    """Detector should pick the right content-type for every file with
    `high` confidence (filename match). Lower confidence is only allowed
    when filenames don't match Rahul's templates — none of the sample
    files should fall into that case."""
    from app.metadata.format_detector import detect, Format

    expected = {
        "databasesv_full_export.rendered.dat":              "dict_databases",
        "tablesv_full_export.rendered.dat":                 "dict_tables",
        "columnsv_full_export.rendered.dat":                "dict_columns",
        "indicesv_full_export.rendered.dat":                "dict_indices",
        "partitioningconstraintsv_full_export.rendered.dat": "dict_partitioning",
        "tabletextv_full_export.rendered.dat":              "dict_tabletext",
    }
    for filename, expected_ct in expected.items():
        content = (_SAMPLE_DIR / filename).read_bytes()
        verdict = detect(content, filename=filename)
        assert verdict.format is Format.FLAT_FILE, filename
        assert verdict.content_type.value == expected_ct, (
            f"{filename}: expected {expected_ct}, got {verdict.content_type.value}"
        )
        assert verdict.confidence == "high", filename


# ──── Batch-level consistency ────

def test_batch_validator_accepts_consistent_sample():
    """All 6 files come from the same extraction run — validate_batch
    must accept and return the canonical (source, run_id) pair."""
    from app.metadata import dict_flat_file_reader as r
    from app.metadata.dict_batch_validator import validate_batch

    files = [
        ("databases",    r.read_databases(_SAMPLE_DIR / _SAMPLE_FILES["databases"])),
        ("tables",       r.read_tables(_SAMPLE_DIR / _SAMPLE_FILES["tables"])),
        ("columns",      r.read_columns(_SAMPLE_DIR / _SAMPLE_FILES["columns"])),
        ("indices",      r.read_indices(_SAMPLE_DIR / _SAMPLE_FILES["indices"])),
        ("partitioning", r.read_partitioning(_SAMPLE_DIR / _SAMPLE_FILES["partitioning"])),
        ("tabletext",    r.read_tabletext(_SAMPLE_DIR / _SAMPLE_FILES["tabletext"])),
    ]
    identity = validate_batch(files)
    assert identity.source_system_name == "Transcend-DevTest"
    assert identity.extract_run_id.startswith("20260429T135225Z_")


def test_batch_validator_rejects_mixed_runs():
    """Mutate one file's tech header to simulate a mixed-run upload —
    validator must raise BatchConsistencyError so we never silently
    persist a corrupted snapshot."""
    from dataclasses import replace
    from app.metadata import dict_flat_file_reader as r
    from app.metadata.dict_batch_validator import (
        validate_batch, BatchConsistencyError,
    )

    dbs = r.read_databases(_SAMPLE_DIR / _SAMPLE_FILES["databases"])
    tbs = r.read_tables(_SAMPLE_DIR / _SAMPLE_FILES["tables"])

    # Mutate the first DB record to a different run_id. Frozen
    # dataclasses → use `replace` to build a divergent copy.
    rogue_tech = replace(dbs[0].tech, extract_run_id="ROGUE_RUN_xxxxxxxx")
    dbs_mixed = [replace(dbs[0], tech=rogue_tech)] + list(dbs[1:])

    with pytest.raises(BatchConsistencyError) as excinfo:
        validate_batch([("databases", dbs_mixed), ("tables", tbs)])
    # Error message should clearly call out the offender — useful for
    # the API consumer trying to fix the upload.
    assert "ROGUE_RUN" in str(excinfo.value) or "different" in str(excinfo.value).lower()


# ──── End-to-end persistence ────

def test_persist_creates_snapshot_and_skips_reimport(tmp_path):
    """Full pipeline: parse → validate → persist → re-import is no-op.

    Uses an isolated temp DB created from scratch so the test never
    touches the demo seed and is order-independent. The persister is
    session-bound (not engine-bound), so we just hand it a session
    against the temp engine — no monkeypatching, no module reloads.

    Verifies counts that are stable across sample regenerations:
      - 1 snapshot row
      - schemas == |union(databases, tables-by-db)|
      - tables  == 10
      - re-import returns the same snapshot_id with skipped_existing=True
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    import app.db.base  # registers all models
    from app.db.base import Base
    from app.metadata import dict_flat_file_reader as r
    from app.metadata.dict_batch_validator import validate_batch
    from app.metadata.dict_persister import persist_batch

    # Brand-new engine pointing at a temp SQLite in tmp_path. The
    # production engine module is never touched.
    db_path = tmp_path / "test_dict.db"
    test_engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(bind=test_engine)

    dbs = r.read_databases(_SAMPLE_DIR / _SAMPLE_FILES["databases"])
    tbs = r.read_tables(_SAMPLE_DIR / _SAMPLE_FILES["tables"])
    cols = r.read_columns(_SAMPLE_DIR / _SAMPLE_FILES["columns"])
    idxs = r.read_indices(_SAMPLE_DIR / _SAMPLE_FILES["indices"])
    parts = r.read_partitioning(_SAMPLE_DIR / _SAMPLE_FILES["partitioning"])
    tts = r.read_tabletext(_SAMPLE_DIR / _SAMPLE_FILES["tabletext"])

    identity = validate_batch([
        ("databases", dbs), ("tables", tbs), ("columns", cols),
        ("indices", idxs), ("partitioning", parts), ("tabletext", tts),
    ])
    assert identity.source_system_name == "Transcend-DevTest"

    with Session(bind=test_engine) as session:
        first = persist_batch(session, identity, dbs, tbs, cols, idxs, parts, tts)
        session.commit()

        assert first.snapshot_id > 0
        assert first.skipped_existing is False
        assert first.tables_created == 10
        # Schemas = union of databases and tables-by-db (some tables
        # reference databases not in the dict extract). >= 10 because
        # tables.dat alone has 10 distinct DBs in the sample.
        assert first.schemas_created >= 10
        assert first.indices_seen == 10
        assert first.partitioning_seen == 10
        assert first.tabletext_seen == 10

        # Re-import: same identity → idempotent skip
        second = persist_batch(session, identity, dbs, tbs, cols, idxs, parts, tts)
        session.commit()
        assert second.skipped_existing is True
        assert second.snapshot_id == first.snapshot_id
