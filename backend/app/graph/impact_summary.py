"""Pre-aggregated impact summaries for the Impact Analysis page.

Why this module
---------------
``POST /impact/batch`` used to compute downstream + upstream graph
walks for every change in a diff at request time. On a 250k-change
Transcend extract that meant 500k recursive-CTE walks, which froze
the browser at 5+ minutes. Even with the v1.15.00 indexes (which made
each individual CTE fast), the per-change loop is fundamentally O(N).

The fix is structural: compute the per-change counts ONCE â€” during
post-ingest â€” and persist them. ``/impact/batch`` then becomes a
paginated read of pre-aggregated rows.

Key trade-offs
--------------
- We recurse to ``max_depth = 3`` rather than the per-request endpoint's
  10. With the inverse-depth scoring (``1/d``) anything past depth 3
  contributes â‰¤0.33 to the score and rarely changes the qualitative
  picture (HIGH / MEDIUM / LOW). Capping the depth bounds the CTE's
  blow-up on dense graphs (a hub with 1000 out-edges at depth 10 is
  catastrophic; at depth 3 it's tractable).

- The summary stores counts + an aggregate score, NOT the per-node
  detail. Per-node lists ARE still available via the single-change
  drill-down endpoint (``POST /impact/{change_id}``), which the UI
  uses on demand from the Changes page.

- Computation is idempotent at the row level: re-running for the same
  change is safe (we ``DELETE`` then re-``INSERT``). Callers that just
  want to skip already-computed changes pass them through
  ``filter_uncomputed()`` first.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent
from app.graph.graph_diff_linker import link_changes_to_graph
from app.graph.graph_models import GraphNode
from app.graph.impact_analyzer import (
    compute_downstream_impact,
    compute_upstream_impact,
)
from app.graph.impact_models import ChangeImpactSummary


logger = logging.getLogger(__name__)


# Depth cap for the pre-aggregation walks. See module docstring for the
# rationale. The single-change drill-down endpoint can use a deeper cap
# because it only walks ONCE per request.
SUMMARY_MAX_DEPTH = 3


# SQLite's default ``SQLITE_MAX_VARIABLE_NUMBER`` is 999. Hitting this
# limit raises ``sqlite3.OperationalError: too many SQL variables``,
# which is what crashed ``/impact/batch`` on the first Transcend test.
# We chunk every ``IN (...)`` query through this cap. Postgres has no
# equivalent limit but the chunking is cheap there too â€” round trips
# scale linearly with chunk count and there are at most ~250 chunks
# even on a 250k-change Transcend extract.
_SQL_IN_CHUNK = 900


def _chunked(items: Sequence[int], size: int = _SQL_IN_CHUNK) -> Iterable[List[int]]:
    """Yield slices of ``items`` no larger than ``size``.

    Local helper rather than a `more_itertools` import â€” the chunking is
    a one-line generator and the dependency would be the only place
    we'd need it.
    """
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def filter_uncomputed(change_ids: Iterable[int]) -> List[int]:
    """Return the subset of ``change_ids`` that don't yet have a summary.

    Used by the post-ingest hook to avoid recomputing summaries for
    changes a previous (interrupted) run already finished. Cheap thanks
    to the ``change_id`` primary key, but at production scale (250k
    changes) we have to chunk the ``IN`` clause around SQLite's
    999-variable limit â€” see ``_SQL_IN_CHUNK``.
    """
    ids = list(change_ids)
    if not ids:
        return []
    existing: set[int] = set()
    with Session(engine) as session:
        for chunk in _chunked(ids):
            existing.update(
                session.execute(
                    select(ChangeImpactSummary.change_id).where(
                        ChangeImpactSummary.change_id.in_(chunk)
                    )
                ).scalars()
            )
    return [cid for cid in ids if cid not in existing]


def compute_summary_for_change(
    change_id: int,
    snapshot_id: int,
    *,
    node_id_by_change: Optional[Dict[int, int]] = None,
) -> Optional[Dict[str, object]]:
    """Compute the impact summary for a single change.

    Returns a dict ready to be persisted into ``change_impact_summary``
    (with ``change_id`` and ``snapshot_id`` filled), or ``None`` when
    the change can't be mapped to a graph node (typically a column-
    level change in a snapshot whose graph_node table only stores
    object-level rows). Callers persist a zero-row when this returns
    ``None`` so the change is still marked as "computed" and the
    /impact/batch endpoint doesn't re-trigger work for it.

    ``node_id_by_change`` lets the batch caller share a single
    ``link_changes_to_graph`` call across many changes â€” the per-change
    cost of the resolver is negligible but the per-snapshot setup is
    not, so passing it in cuts O(N) overhead in tight loops.
    """
    if node_id_by_change is None:
        node_id_by_change = link_changes_to_graph(snapshot_id)

    node_id = node_id_by_change.get(change_id)
    if node_id is None:
        return None

    downstream = compute_downstream_impact(
        node_id, snapshot_id, max_depth=SUMMARY_MAX_DEPTH
    )
    upstream = compute_upstream_impact(
        node_id, snapshot_id, max_depth=SUMMARY_MAX_DEPTH
    )

    direct_count = sum(1 for item in downstream if item.get("depth", 0) == 1)
    indirect_count = sum(1 for item in downstream if item.get("depth", 0) > 1)
    score = round(
        sum(item.get("impact_score", 0.0) for item in downstream)
        + sum(item.get("impact_score", 0.0) for item in upstream),
        4,
    )
    max_depth = max(
        (item.get("depth", 0) for item in downstream),
        default=0,
    )
    max_depth_up = max(
        (item.get("depth", 0) for item in upstream),
        default=0,
    )
    max_depth = max(max_depth, max_depth_up)

    return {
        "change_id": change_id,
        "snapshot_id": snapshot_id,
        "direct_count": direct_count,
        "indirect_count": indirect_count,
        "impact_score": score,
        "max_depth": max_depth,
    }


def persist_summaries_for_pair(
    snapshot_to: int,
    change_ids: Optional[Sequence[int]] = None,
    *,
    skip_existing: bool = True,
    progress_cb: Optional[callable] = None,
) -> int:
    """Compute and persist impact summaries for changes in a snapshot.

    Parameters
    ----------
    snapshot_to:
        The post-change snapshot whose graph topology is used for the
        walks. Matches ``ChangeEvent.snapshot_to``.
    change_ids:
        Optional explicit subset of change IDs to summarise. When
        omitted, every change with ``snapshot_to == snapshot_to`` is
        included.
    skip_existing:
        When True (default), changes that already have a row in
        ``change_impact_summary`` are skipped â€” the operation becomes a
        no-op for already-computed snapshots, which is what the
        post-ingest hook wants. Set False when re-computing after a
        graph rebuild.
    progress_cb:
        Optional callback ``fn(done: int, total: int) -> None`` invoked
        every 200 rows. Used by the lazy-backfill path in
        ``/impact/batch`` to push progress updates to the frontend.

    Returns
    -------
    The number of summary rows actually persisted (zero when nothing
    was new and ``skip_existing`` was True).
    """
    # Resolve change list. Pulling change_ids in one query is cheap
    # thanks to the (snapshot_from, snapshot_to) index added in
    # v1.15.00.
    with Session(engine) as session:
        if change_ids is None:
            change_ids = session.execute(
                select(ChangeEvent.change_id).where(
                    ChangeEvent.snapshot_to == snapshot_to
                )
            ).scalars().all()

    target_ids = list(change_ids)
    if skip_existing:
        target_ids = filter_uncomputed(target_ids)

    if not target_ids:
        return 0

    # Resolve once per snapshot â€” link_changes_to_graph reads the entire
    # change_event â†” graph_node mapping for the snapshot, which is far
    # cheaper amortised across many changes than calling it per change.
    node_id_by_change = link_changes_to_graph(snapshot_to)

    # Pre-load the full ChangeEvent set we'll need, since the persist
    # loop only needs (change_id, snapshot_to) but the resolver uses
    # other fields. We keep the session out of the hot loop to avoid
    # autoflush overhead on every persist.
    rows_to_insert: List[Dict[str, object]] = []
    started = time.perf_counter()
    total = len(target_ids)

    for idx, cid in enumerate(target_ids):
        summary = compute_summary_for_change(
            cid, snapshot_to, node_id_by_change=node_id_by_change
        )
        if summary is None:
            # Persist a zero-row so the lazy-backfill path doesn't keep
            # retrying changes that legitimately have no graph mapping
            # (column-level changes etc.). The /impact/batch UI happily
            # renders zero counts as "no impact".
            summary = {
                "change_id": cid,
                "snapshot_id": snapshot_to,
                "direct_count": 0,
                "indirect_count": 0,
                "impact_score": 0.0,
                "max_depth": 0,
            }
        summary["computed_at"] = datetime.now(UTC)
        rows_to_insert.append(summary)

        # Surface progress every 200 rows; cheap enough to not bother
        # batching tighter, infrequent enough not to flood logs.
        if progress_cb is not None and (idx + 1) % 200 == 0:
            progress_cb(idx + 1, total)

    # Persist in a single bulk write. We delete any existing rows for
    # this set of change_ids first to make the operation idempotent
    # under non-skip_existing usage. The ``IN (...)`` clause is chunked
    # for the same SQLite-variable-limit reason as ``filter_uncomputed``.
    with Session(engine) as session:
        if not skip_existing:
            for chunk in _chunked(target_ids):
                session.execute(
                    delete(ChangeImpactSummary).where(
                        ChangeImpactSummary.change_id.in_(chunk)
                    )
                )
        session.bulk_insert_mappings(ChangeImpactSummary, rows_to_insert)
        session.commit()

    elapsed = time.perf_counter() - started
    logger.info(
        "[impact-summary] persisted %d row(s) for snapshot %d in %.2fs",
        len(rows_to_insert),
        snapshot_to,
        elapsed,
    )
    if progress_cb is not None:
        progress_cb(total, total)

    return len(rows_to_insert)
