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
from typing import Iterable, List, Optional, Set, Tuple

from .dict_flat_file_reader import (
    DatabaseRecord, TableRecord, ColumnRecord, IndexRecord,
    PartitioningRecord, TableTextRecord, TechFields,
)


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
        BatchConsistencyError: if files disagree, or all files are empty.
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

    return next(iter(distinct_ids))
