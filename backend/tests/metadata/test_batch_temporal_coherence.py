"""Tests for the temporal-coherence checks added in v1.13.01.

Two checks are added on top of the source+run_id consistency:
  - All files share the same `snapshot_date`.
  - All files' `extracted_at_utc` are within the configured drift
    window (today: 2 hours).

Both are defence-in-depth — `extract_run_id` already separates distinct
runs into distinct snapshots correctly, so these checks only fire on
edge cases where files share a run_id but were stitched from a paused
or partially re-run extraction.

Strategy: build minimal in-memory record sets via `dataclasses.replace`,
mutate one tech field at a time, assert the validator either accepts
(consistent) or rejects (drifted) accordingly.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.metadata.dict_flat_file_reader import (
    DatabaseRecord, TableRecord, TechFields,
)
from app.metadata.dict_batch_validator import (
    validate_batch, BatchConsistencyError,
    MAX_TIMESTAMP_DRIFT_WITHIN_BATCH,
)


# ──── Test fixtures (plain dataclass instances, no DB / no files) ────

def _tech(extracted_at: str = "2026-04-29 09:00:00.000000+00:00",
          snapshot_date: str = "2026-04-29") -> TechFields:
    """Build a TechFields with known constants. Source + run_id are
    fixed across all helpers so the temporal checks are isolated from
    the identity check."""
    return TechFields(
        source_system_name="TestSrc",
        extract_run_id="RUN_001",
        extracted_at_utc=extracted_at,
        snapshot_date=snapshot_date,
    )


def _db_record(tech: TechFields, name: str = "DB_X") -> DatabaseRecord:
    return DatabaseRecord(
        tech=tech, database_name=name,
        owner_name=None, creator_name=None,
        create_timestamp=None, last_alter_name=None,
        last_alter_timestamp=None, comment_string=None,
        perm_space=None, spool_space=None, temp_space=None,
    )


def _table_record(tech: TechFields, name: str = "T_X") -> TableRecord:
    return TableRecord(
        tech=tech, database_name="DB_X", table_name=name,
        table_kind="T", creator_name=None, create_timestamp=None,
        last_alter_name=None, last_alter_timestamp=None,
        comment_string=None, protection_type=None,
        journal_flag=None, check_opt=None,
    )


# ──── snapshot_date check ────

def test_accepts_files_with_same_snapshot_date():
    """Baseline: identical tech fields → validator returns the identity
    cleanly. Anchors the rest of the suite."""
    t = _tech()
    identity = validate_batch([
        ("databases", [_db_record(t)]),
        ("tables", [_table_record(t)]),
    ])
    assert identity.source_system_name == "TestSrc"
    assert identity.extract_run_id == "RUN_001"


def test_rejects_files_crossing_midnight():
    """Two files with the same run_id but different snapshot_date
    means the orchestration was paused across a day boundary — a
    coherent run finishes within hours, never crosses midnight.
    Reject loudly."""
    early = _tech(snapshot_date="2026-04-29")
    late = _tech(snapshot_date="2026-04-30")
    with pytest.raises(BatchConsistencyError) as excinfo:
        validate_batch([
            ("databases", [_db_record(early)]),
            ("tables", [_table_record(late)]),
        ])
    msg = str(excinfo.value)
    assert "snapshot_date" in msg
    assert "2026-04-29" in msg and "2026-04-30" in msg


def test_snapshot_date_error_lists_offending_files():
    """The error message must name which file had which date so the
    user knows where to look. Not just 'something is off'."""
    early = _tech(snapshot_date="2026-04-29")
    late = _tech(snapshot_date="2026-04-30")
    with pytest.raises(BatchConsistencyError) as excinfo:
        validate_batch([
            ("databases", [_db_record(early)]),
            ("tables", [_table_record(late)]),
        ])
    msg = str(excinfo.value)
    assert "databases" in msg
    assert "tables" in msg


# ──── extracted_at_utc drift check ────

def test_accepts_files_within_drift_window():
    """Files extracted seconds apart (the normal case) must pass.
    The Sample 1 from Rahul has ~1.5 minutes of drift across 6 files —
    well within the 2-hour window."""
    t1 = _tech(extracted_at="2026-04-29 09:00:00.000000+00:00")
    t2 = _tech(extracted_at="2026-04-29 09:01:30.000000+00:00")
    identity = validate_batch([
        ("databases", [_db_record(t1)]),
        ("tables", [_table_record(t2)]),
    ])
    assert identity.extract_run_id == "RUN_001"


def test_accepts_files_at_window_boundary():
    """Exactly at the drift limit must pass — strict less-than is
    correct (anything *over* fails). Customers running near the limit
    shouldn't get bitten by float-equal weirdness."""
    t1 = _tech(extracted_at="2026-04-29 09:00:00.000000+00:00")
    t2 = _tech(
        extracted_at=(
            f"2026-04-29 "
            f"{9 + int(MAX_TIMESTAMP_DRIFT_WITHIN_BATCH.total_seconds() // 3600):02d}"
            ":00:00.000000+00:00"
        )
    )
    # No exception → passes
    validate_batch([
        ("databases", [_db_record(t1)]),
        ("tables", [_table_record(t2)]),
    ])


def test_rejects_files_drifting_beyond_window():
    """Files extracted more than the configured window apart — paused
    orchestration or hand-stitched batch."""
    t1 = _tech(extracted_at="2026-04-29 09:00:00.000000+00:00")
    # 2 hours and 1 minute apart — just over the limit.
    t2 = _tech(extracted_at="2026-04-29 11:01:00.000000+00:00")
    with pytest.raises(BatchConsistencyError) as excinfo:
        validate_batch([
            ("databases", [_db_record(t1)]),
            ("tables", [_table_record(t2)]),
        ])
    msg = str(excinfo.value)
    # Error should call out both endpoints by filename so the user
    # knows the gap is real, not a vague "timestamps are weird".
    assert "databases" in msg
    assert "tables" in msg
    assert "earliest" in msg and "latest" in msg


def test_rejects_huge_drift_with_clear_message():
    """A 12-hour gap is the easy-to-imagine pause scenario. Make sure
    the human-readable message mentions the actual span."""
    t1 = _tech(extracted_at="2026-04-29 09:00:00.000000+00:00")
    t2 = _tech(extracted_at="2026-04-29 21:00:00.000000+00:00")
    with pytest.raises(BatchConsistencyError) as excinfo:
        validate_batch([
            ("databases", [_db_record(t1)]),
            ("tables", [_table_record(t2)]),
        ])
    msg = str(excinfo.value)
    assert "12:00:00" in msg or "12 hours" in msg.lower() or "wall time" in msg


# ──── Degraded behaviour ────

def test_unparseable_timestamp_does_not_crash():
    """If `extracted_at_utc` is unparseable for some reason, the
    timestamp check should silently degrade (return without error)
    rather than block the ingest. The reader's arity check would
    catch a truly malformed record before this code runs anyway."""
    t1 = _tech(extracted_at="not-a-timestamp")
    t2 = _tech(extracted_at="also-garbage")
    # Should NOT raise — timestamp check skips when parsing fails.
    identity = validate_batch([
        ("databases", [_db_record(t1)]),
        ("tables", [_table_record(t2)]),
    ])
    assert identity.extract_run_id == "RUN_001"


def test_single_file_skips_temporal_check():
    """Only one file → nothing to cross-check. Don't trip the user up
    on partial uploads (which the persister handles fine)."""
    t = _tech()
    identity = validate_batch([("databases", [_db_record(t)])])
    assert identity.extract_run_id == "RUN_001"
