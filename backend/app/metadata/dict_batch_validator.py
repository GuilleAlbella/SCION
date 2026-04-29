from __future__ import annotations

"""Batch consistency validation for data-dictionary uploads.

A dict ingest accepts up to 6 files in one call:
  databases / tables / columns / indices / partitioning / tabletext.

All 6 must come from the **same extraction run** — otherwise we'd be
mixing snapshots silently, which is the worst kind of data corruption.
Rahul's extractor stamps every record with `source_system_name` and
`extract_run_id` (generated once per orchestration run, see his
`run_metadata_extracts.py`), so we can validate consistency without
trusting filenames or upload metadata.

Rules enforced
1. **Same source_system_name** across every record of every file.
2. **Same extract_run_id** across every record of every file.
3. At least one of the 6 files must be present (no empty batch).

What this module does NOT do
- Decide which file is which view (that's `format_detector.py`).
- Persist anything (that's `dict_persister.py`).
- Cross-check against past snapshots — first or fiftieth, the batch
  has to be internally consistent before we even look at it.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Set, Tuple

from .dict_flat_file_reader import (
    DatabaseRecord, TableRecord, ColumnRecord, IndexRecord,
    PartitioningRecord, TableTextRecord, TechFields,
)


# ──── Timestamp drift policy ────
# Within a single extract_run_id, the 6 SQL queries run sequentially —
# they SHOULD finish within minutes. We accept up to 2 hours to give
# Lloyds-scale customers (500M+ relationships, TPT high-volume mode)
# room to run multi-million-row exports back-to-back. Anything beyond
# that almost certainly means the orchestration was paused or files
# were assembled from a partial / re-run.
#
# Tightening this is cheap; loosening it requires a fresh discussion
# because the whole point of the check is "files are temporally
# coherent within a single run".
MAX_TIMESTAMP_DRIFT_WITHIN_BATCH = timedelta(hours=2)


# Anything with a `.tech: TechFields` attribute. Using a Protocol would
# be cleaner but the 6 dataclasses are concrete and frozen — a Union is
# fine and keeps imports short.
DictRecord = (
    DatabaseRecord | TableRecord | ColumnRecord
    | IndexRecord | PartitioningRecord | TableTextRecord
)


@dataclass(frozen=True)
class BatchIdentity:
    """The (source, run) pair that defines an extraction run.

    Used as the snapshot key on the SCION side — one batch ⇔ one
    SCION snapshot.
    """
    source_system_name: str
    extract_run_id: str

    @property
    def snapshot_label(self) -> str:
        """Human-friendly label for logs and UI, e.g.
        `Transcend-DevTest @ 20260429T135225Z_1eea...64cb7`."""
        return f"{self.source_system_name} @ {self.extract_run_id}"


class BatchConsistencyError(ValueError):
    """Raised when files in a batch disagree on source/run identity.

    Subclass of `ValueError` so route handlers can map it to a 400
    automatically while still distinguishing it from generic ValueErrors.
    """


def collect_identities(
    records: Iterable[DictRecord],
) -> Set[BatchIdentity]:
    """Gather every distinct (source_system_name, extract_run_id) seen.

    Walking each record (instead of trusting just the first) catches
    the rare-but-real case where a file has rows from two runs —
    which would mean Rahul's pipeline merged outputs incorrectly.
    Cheap to do (frozen dataclass + set lookup is O(n)).
    """
    seen: Set[BatchIdentity] = set()
    for r in records:
        seen.add(BatchIdentity(
            source_system_name=r.tech.source_system_name,
            extract_run_id=r.tech.extract_run_id,
        ))
    return seen


def _parse_extracted_at(s: str) -> Optional[datetime]:
    """Parse Rahul's `extracted_at_utc` field into a tz-aware datetime.

    The wire format is `YYYY-MM-DD HH:MM:SS.ffffff±HH:MM` (e.g.
    `2026-04-29 09:52:32.600000-04:00`). Python 3.11+'s
    `datetime.fromisoformat` handles this directly even with the
    space separator. We wrap to None on parse failure so the
    timestamp check degrades to a warning-equivalent (skipped)
    instead of crashing the whole ingest — record-level corruption
    is the file reader's job to surface, not ours.
    """
    try:
        return datetime.fromisoformat(s.strip())
    except (ValueError, AttributeError):
        return None


def _check_temporal_coherence(
    files: List[Tuple[str, List[DictRecord]]],
) -> None:
    """Verify the 6 files were extracted as part of one orchestration.

    Two checks:
      1. Every file shares the same `snapshot_date` — fast, catches
         the easy "files cross midnight" case.
      2. Every file's `extracted_at_utc` is within
         `MAX_TIMESTAMP_DRIFT_WITHIN_BATCH` of the others — catches
         pauses, partial re-runs, or someone hand-stitching files
         from different runs that happen to share a run_id.

    Both checks rely on Rahul's contract: every record in a file
    has identical tech fields (because they're all from the same
    SQL query). We sample the first record per file rather than
    walking everything — O(n_files) instead of O(n_records).
    """
    # Sample one tech-field set per file. Empty files contribute nothing.
    samples: List[Tuple[str, TechFields]] = []
    for name, records in files:
        if records:
            samples.append((name, records[0].tech))
    if len(samples) < 2:
        # Single-file batch — nothing to cross-check temporally.
        return

    # ──── Check 1: same snapshot_date everywhere ────
    dates_by_file: dict[str, str] = {n: t.snapshot_date for n, t in samples}
    distinct_dates = set(dates_by_file.values())
    if len(distinct_dates) > 1:
        lines = [
            "Inconsistent batch: files were extracted on different dates "
            f"({len(distinct_dates)} distinct snapshot_date values):"
        ]
        for name, date in dates_by_file.items():
            lines.append(f"  - {name}: snapshot_date={date}")
        lines.append(
            "All 6 files of one extraction run should share the same "
            "`snapshot_date`. Re-extract from a single orchestration run."
        )
        raise BatchConsistencyError("\n".join(lines))

    # ──── Check 2: extracted_at_utc within drift window ────
    # Files run sequentially, so the timestamps differ — but only by
    # the time it took to run each query. A drift larger than the
    # configured window means the run wasn't continuous.
    parsed: List[Tuple[str, datetime]] = []
    for name, t in samples:
        ts = _parse_extracted_at(t.extracted_at_utc)
        if ts is not None:
            parsed.append((name, ts))
    if len(parsed) < 2:
        # Couldn't parse enough timestamps to compare — don't block on
        # what's effectively a soft signal. The reader would have
        # already failed on a malformed record.
        return

    earliest_name, earliest = min(parsed, key=lambda p: p[1])
    latest_name, latest = max(parsed, key=lambda p: p[1])
    drift = latest - earliest
    if drift > MAX_TIMESTAMP_DRIFT_WITHIN_BATCH:
        lines = [
            f"Inconsistent batch: files span {drift} of wall time "
            f"(max allowed: {MAX_TIMESTAMP_DRIFT_WITHIN_BATCH}):",
            f"  - earliest: {earliest_name} at {earliest.isoformat()}",
            f"  - latest:   {latest_name} at {latest.isoformat()}",
            "A normal extraction run completes in minutes (hours at most "
            "for very large customers). Drift this large suggests the "
            "orchestration was paused, partially re-run, or files were "
            "assembled from separate runs. Re-extract.",
        ]
        raise BatchConsistencyError("\n".join(lines))


def validate_batch(
    files: List[Tuple[str, List[DictRecord]]],
) -> BatchIdentity:
    """Validate that every record in every file shares the same identity.

    Args:
        files: list of (filename, records) tuples. Empty record lists
               are allowed (a customer might send an empty
               `partitioningconstraintsv` if no partitioned tables
               exist) but at least one file must be non-empty.

    Returns:
        The single BatchIdentity that all files agree on.

    Raises:
        BatchConsistencyError: if files disagree on identity, span
        different snapshot_dates, or have extracted_at_utc drift
        beyond `MAX_TIMESTAMP_DRIFT_WITHIN_BATCH`. Each path emits a
        message describing exactly which files broke which rule.
    """
    if not files:
        raise BatchConsistencyError("Empty batch: no files provided.")

    # Per-file identity sets, kept around so the error message can
    # tell the user which file disagreed with which.
    per_file: List[Tuple[str, Set[BatchIdentity]]] = [
        (name, collect_identities(records)) for name, records in files
    ]

    # Drop empty files for the consistency check itself, but remember
    # we did so — if the entire batch is empty we still want to error.
    non_empty = [(n, s) for n, s in per_file if s]
    if not non_empty:
        raise BatchConsistencyError(
            "Empty batch: every file parsed to zero records. "
            "Check the source files weren't truncated."
        )

    # Each file individually must have exactly one identity. Anything
    # else means a single file has rows from multiple runs — that's a
    # producer-side bug, not something we can recover from.
    for name, ids in non_empty:
        if len(ids) > 1:
            raise BatchConsistencyError(
                f"File `{name}` mixes records from {len(ids)} different "
                f"extraction runs: {sorted(i.snapshot_label for i in ids)}. "
                "This indicates the producer concatenated outputs from "
                "multiple runs — re-extract from a single run."
            )

    # Now every non-empty file has exactly one identity. Compare them.
    distinct_ids: Set[BatchIdentity] = set()
    for _, ids in non_empty:
        distinct_ids.update(ids)

    if len(distinct_ids) > 1:
        # Build a clear diff so the user can see who disagrees with whom.
        lines = [
            f"Inconsistent batch: files come from {len(distinct_ids)} "
            f"different extraction runs:"
        ]
        for name, ids in non_empty:
            for i in ids:
                lines.append(f"  - {name}: {i.snapshot_label}")
        lines.append(
            "Re-extract all 6 files together so they share the same "
            "`extract_run_id` (generated once per orchestration run)."
        )
        raise BatchConsistencyError("\n".join(lines))

    # Defence-in-depth: even with matching identity, verify the files
    # were extracted within a reasonable wall-clock window. Catches
    # paused orchestrations and hand-stitched batches that happen to
    # share a run_id. See `_check_temporal_coherence` for the policy.
    _check_temporal_coherence(files)

    return next(iter(distinct_ids))
