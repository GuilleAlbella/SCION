from __future__ import annotations

"""In-memory progress tracker for the dict-import endpoint.

The dict-import handler is a long-running synchronous request — for
Rahul's full Transcend-DevTest extract it sits on the wire for ~6
minutes. The browser can't show real progress while waiting on the
POST response, but it CAN poll a parallel `/progress/{import_id}`
endpoint while the original POST is in flight.

Architecture:
  1. Frontend generates `import_id = crypto.randomUUID()` and sends it
     as a form field on the POST.
  2. Backend handler calls `init(import_id, steps)` at start, then
     `start_step / update_progress / end_step` as it walks through
     the pipeline.
  3. Frontend polls `GET .../progress/{import_id}` every ~1 s while
     the POST is open. Server reads the same in-memory dict and
     returns a snapshot.
  4. On completion (success or error) `mark_finished` flips the
     terminal flag; the entry stays in memory long enough for the
     last poll to see "done", then is GC'd by `_evict_stale`.

Thread-safety: FastAPI runs sync handlers in a thread pool, so the
POST handler (writer) and the GET handler (reader) run on different
threads. Python's `dict` operations on individual keys are atomic
under the GIL, but compound state mutations (e.g. "find step by name
and bump its progress") need a lock to be safe. We use a single
module-level `Lock` because total contention is minimal — at most
one POST per active import + occasional polls.

This is in-memory only — restarting uvicorn loses every in-flight
import's progress. Acceptable: the import itself survives (it's
running in the same Python process), just the UI loses real-time
feedback. For multi-process deployments we'd swap this for Redis or
similar; today single-process uvicorn is the only target.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional


# Step status values, ordered so the UI can render them with
# progressively-stronger visual treatments. `pending` means we know
# this step exists but haven't started it; `running` means it's the
# current focus; `done` means we've moved on; `error` is terminal
# for the whole pipeline.
StepStatus = Literal["pending", "running", "done", "error"]


@dataclass
class StepState:
    """One row in the progress checklist."""

    name: str
    label: str
    status: StepStatus = "pending"
    # 0..1 fractional progress for steps that have meaningful
    # sub-progress (uploads counted in bytes, persist counted in
    # rows). `None` means "indeterminate / no sub-progress".
    progress: Optional[float] = None
    # Free-form text rendered next to the bar, e.g. "4.2M / 9.8M
    # rows" or "33.4 MB/s". Caller decides what's useful.
    caption: Optional[str] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None

    @property
    def elapsed_seconds(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.ended_at if self.ended_at is not None else time.perf_counter()
        return end - self.started_at

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "status": self.status,
            "progress": self.progress,
            "caption": self.caption,
            "elapsed_seconds": self.elapsed_seconds,
        }


@dataclass
class ImportProgress:
    """Full progress record for one ongoing import."""

    import_id: str
    steps: List[StepState] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)
    ended_at: Optional[float] = None
    status: Literal["running", "done", "error", "cancelled"] = "running"
    error_message: Optional[str] = None
    # Cooperative-cancellation flag. The dict-import handler polls this
    # at known checkpoints (between bulk-insert batches) and raises
    # `ImportCancelled` if it's set. Rollback then unwinds whatever
    # rows were already inserted in the open transaction.
    cancel_requested: bool = False

    @property
    def total_elapsed_seconds(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.perf_counter()
        return end - self.started_at

    def to_dict(self) -> dict:
        return {
            "import_id": self.import_id,
            "status": self.status,
            "error_message": self.error_message,
            "total_elapsed_seconds": self.total_elapsed_seconds,
            "cancel_requested": self.cancel_requested,
            "steps": [s.to_dict() for s in self.steps],
        }


class ImportCancelled(Exception):
    """Raised by checkpoint helpers when the client requested cancellation.

    The dict-import handler catches this near the persist boundary and
    rolls back the in-flight transaction so the partially-inserted
    snapshot never lands in the DB.
    """


# ──── Module-level state ────

_lock = threading.Lock()
_imports: Dict[str, ImportProgress] = {}

# How long to keep finished entries around before evicting. The UI's
# polling interval is ~1 s, so 60 s is plenty for the last
# "status=done" poll to land. Anything stale beyond this gets
# garbage-collected on the next mutation.
_STALE_TTL_SECONDS = 60.0


def _evict_stale() -> None:
    """Drop finished imports older than `_STALE_TTL_SECONDS`.

    Called opportunistically from every mutator so we don't need a
    background thread. O(n) over active imports — fine because n is
    typically 1 (the user is doing one import at a time on a single
    laptop).
    """
    cutoff = time.perf_counter() - _STALE_TTL_SECONDS
    stale = [
        iid for iid, p in _imports.items()
        if p.ended_at is not None and p.ended_at < cutoff
    ]
    for iid in stale:
        _imports.pop(iid, None)


# ──── Public API ────


def init(import_id: str, steps: List[tuple[str, str]]) -> None:
    """Register a new import with its checklist.

    `steps` is a list of `(name, label)` pairs in display order:
      - `name` is a stable machine identifier (matches the value
        passed to subsequent `start_step` / `end_step` calls).
      - `label` is the user-facing string ("Persist columns",
        "Build graph", etc).
    """
    with _lock:
        _evict_stale()
        _imports[import_id] = ImportProgress(
            import_id=import_id,
            steps=[StepState(name=n, label=l) for n, l in steps],
        )


def start_step(
    import_id: str, step_name: str, caption: Optional[str] = None,
) -> None:
    """Mark a step as currently running."""
    with _lock:
        prog = _imports.get(import_id)
        if prog is None:
            return
        for s in prog.steps:
            if s.name == step_name:
                s.status = "running"
                s.started_at = time.perf_counter()
                if caption is not None:
                    s.caption = caption
                return


def update_progress(
    import_id: str,
    step_name: str,
    progress: Optional[float] = None,
    caption: Optional[str] = None,
) -> None:
    """Bump sub-progress on the currently-running step.

    Either or both of `progress` / `caption` may be `None` — `None`
    leaves the existing value untouched. `progress` is clamped to
    [0, 1] so a slightly-overshooting estimate doesn't render past
    100 %.
    """
    with _lock:
        prog = _imports.get(import_id)
        if prog is None:
            return
        for s in prog.steps:
            if s.name == step_name:
                if progress is not None:
                    s.progress = max(0.0, min(1.0, progress))
                if caption is not None:
                    s.caption = caption
                return


def end_step(
    import_id: str, step_name: str, caption: Optional[str] = None,
) -> None:
    """Mark a step as completed successfully."""
    with _lock:
        prog = _imports.get(import_id)
        if prog is None:
            return
        for s in prog.steps:
            if s.name == step_name:
                s.status = "done"
                s.ended_at = time.perf_counter()
                if s.progress is None:
                    s.progress = 1.0
                if caption is not None:
                    s.caption = caption
                return


def mark_finished(
    import_id: str,
    ok: bool = True,
    error_message: Optional[str] = None,
) -> None:
    """Flip the terminal flag on the whole import."""
    with _lock:
        prog = _imports.get(import_id)
        if prog is None:
            return
        prog.ended_at = time.perf_counter()
        prog.status = "done" if ok else "error"
        prog.error_message = error_message


def get(import_id: str) -> Optional[ImportProgress]:
    """Return the progress record for `import_id`, or None if unknown."""
    with _lock:
        _evict_stale()
        return _imports.get(import_id)


def request_cancel(import_id: str) -> bool:
    """Flag an in-flight import for cooperative cancellation.

    Returns True if the import was found and flagged, False if no
    such import exists (or it already finished). The handler polls
    `is_cancel_requested` at checkpoints and raises `ImportCancelled`
    when it sees the flag — so the actual stop happens at the next
    checkpoint, typically within a few hundred ms.
    """
    with _lock:
        prog = _imports.get(import_id)
        if prog is None or prog.ended_at is not None:
            return False
        prog.cancel_requested = True
        return True


def is_cancel_requested(import_id: Optional[str]) -> bool:
    """Cheap check for the cancel flag, callable from hot paths.

    `import_id` is `Optional` so call sites that may or may not have
    one (e.g. the bulk-insert helpers when invoked outside the API
    layer) can call this unconditionally and get `False` for the
    "no tracking registered" case.
    """
    if import_id is None:
        return False
    with _lock:
        prog = _imports.get(import_id)
        return prog is not None and prog.cancel_requested


# Step name + label catalogue used by the dict-import handler. Kept
# in one place so the UI shows the same labels in the same order
# regardless of which code path emits the updates.
DICT_IMPORT_STEPS: List[tuple[str, str]] = [
    ("upload", "Upload files"),
    ("parse_files", "Parse files"),
    ("validate_identity", "Validate batch identity"),
    ("persist_data", "Persist data"),
    ("post_ingest", "Build graph & metrics"),
]
