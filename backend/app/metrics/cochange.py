from __future__ import annotations

"""Co-change association mining over the change_event history.

Feature #2 of the v1.07 data-science pack. We apply the **market-basket
analysis** algorithm (Agrawal/Srikant 1994) to SCION's change history:

    "transaction" = one snapshot-delta
    "item"        = one object that changed in that delta
    "rule A → B"  = P(B changed | A changed) across all deltas

For each pair `(A, B)` of objects that have co-changed at least once,
we compute three standard association metrics:

- **support(A, B)** = fraction of deltas where BOTH changed
- **confidence(A → B)** = P(B | A) = support(A, B) / support(A)
- **lift(A, B)** = confidence(A → B) / P(B)

`lift > 1` means B changes MORE than random chance when A changes —
i.e. the two are *historically coupled*. This surfaces invisible
relationships the lineage graph cannot capture:
  - Cross-domain tables that the same team tweaks every release.
  - DEV/UAT/PROD triplets that evolve in lockstep.
  - Business-convention couplings not modeled by SQL lineage.

It's deliberately cheap (pairwise, no frequent-itemset expansion).
Returns top-N pairs by lift, with a minimum support threshold to avoid
surfacing noise from one-off coincidences.
"""

from dataclasses import dataclass, asdict
from itertools import combinations
from typing import Dict, List, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent


# Minimum number of deltas ("transactions") in which a pair must appear
# before we bother reporting it. Below this, lift estimates are too noisy.
DEFAULT_MIN_PAIR_SUPPORT = 2

# Minimum lift threshold. 1.0 = random co-occurrence; 2.0 = twice as
# likely as chance; > 3.0 = strong coupling.
DEFAULT_MIN_LIFT = 1.5

# Cap on history depth (most recent N consecutive snapshot pairs scanned).
# Without this, mining the entire change_event table is O(rows) on every
# request — a 250k-row Transcend extract turned the Intelligence page
# into a multi-second wait per click. 20 pairs ≈ a quarter of operational
# history for a typical weekly-import shop, which is plenty of signal
# for Apriori-style mining.
DEFAULT_MAX_HISTORY_PAIRS = 20

# Maximum basket size (unique table-level objects per delta) before a
# transaction is dropped from the mining input. Deltas with more objects
# than this cap are mass-refresh events (full schema reloads, large
# migrations) where every object changes together — they don't generate
# meaningful co-change signal and dominate the combinations step with
# O(N²) pairs. At N=245k that's ~30 billion pairs; the algo would never
# finish. By skipping these "noisy" transactions we keep the mining
# bounded. Set to 0 to disable the cap (not recommended on production).
DEFAULT_MAX_BASKET_SIZE = 500


@dataclass
class CoChangePair:
    """One directional association rule A → B with full metrics."""
    object_a: str
    object_b: str
    co_occurrences: int    # # de deltas con ambos
    occurrences_a: int     # # de deltas con A
    occurrences_b: int     # # de deltas con B
    total_deltas: int      # universo
    support: float         # support(A, B)
    confidence: float      # confidence(A → B)
    lift: float            # lift(A, B)


def _load_deltas_as_transactions(
    max_history_pairs: int = DEFAULT_MAX_HISTORY_PAIRS,
    max_basket_size: int = DEFAULT_MAX_BASKET_SIZE,
) -> List[Set[str]]:
    """Return one `set[object_identifier]` per snapshot delta.

    A "delta" here = one (snapshot_from, snapshot_to) pair. We collapse
    the granular column-level changes up to their parent table, because
    co-change at column level is too sparse to yield useful lift at
    demo data sizes.

    History cap: only the ``max_history_pairs`` most recent consecutive
    snapshot pairs are scanned. Without this, every cochange request
    on a 250k-row ``change_event`` table loaded all of them — multi-
    second latency per click. The cap is on number of *deltas* (pair
    transactions), not raw change-event rows; one delta usually
    contains a few hundred to a few thousand changes.
    """
    with Session(bind=engine) as session:
        # Pre-flight: which pairs are in scope? We pull distinct
        # (snapshot_from, snapshot_to) tuples sorted descending by the
        # ending snapshot, take the top N, and filter the bulk fetch
        # by them. The (snapshot_from, snapshot_to) composite index
        # added in v1.15.00 makes both the distinct scan and the
        # filtered fetch indexed.
        pair_rows = session.execute(
            select(ChangeEvent.snapshot_from, ChangeEvent.snapshot_to)
            .distinct()
            .order_by(ChangeEvent.snapshot_to.desc(), ChangeEvent.snapshot_from.desc())
            .limit(max_history_pairs)
        ).all()
        recent_pairs = [(int(sf), int(st)) for sf, st in pair_rows]
        if not recent_pairs:
            return []

        from sqlalchemy import and_, or_
        pair_filter = or_(
            *[
                and_(
                    ChangeEvent.snapshot_from == sf,
                    ChangeEvent.snapshot_to == st,
                )
                for sf, st in recent_pairs
            ]
        )

        rows = session.execute(
            select(
                ChangeEvent.snapshot_from,
                ChangeEvent.snapshot_to,
                ChangeEvent.object_identifier,
                ChangeEvent.object_type,
            )
            .where(pair_filter)
        ).all()

    # Collapse column changes to parent table so the basket level stays
    # consistent (otherwise column-heavy changes swamp table-level pairs).
    by_delta: Dict[Tuple[int, int], Set[str]] = {}
    for snap_from, snap_to, ident, otype in rows:
        parent = _collapse_to_table(ident, otype)
        if not parent:
            continue
        by_delta.setdefault((snap_from, snap_to), set()).add(parent)

    # Drop baskets with too many objects: they are mass-refresh events
    # where everything changed at once and produce O(N²) pairs that
    # make the combinations step hang. A cap of 0 disables the filter.
    if max_basket_size > 0:
        kept = [s for s in by_delta.values() if 2 <= len(s) <= max_basket_size]
    else:
        kept = [s for s in by_delta.values() if len(s) >= 2]
    return kept


def _collapse_to_table(identifier: str, object_type: str) -> str | None:
    """Strip a column suffix so e.g. `core_banking.loans.principal` →
    `core_banking.loans`. Leaves schema-level identifiers alone.
    """
    if not identifier:
        return None
    parts = identifier.split(".")
    if object_type == "COLUMN" and len(parts) >= 3:
        return ".".join(parts[:2])
    return identifier


def mine_cochange_pairs(
    min_pair_support: int = DEFAULT_MIN_PAIR_SUPPORT,
    min_lift: float = DEFAULT_MIN_LIFT,
    top_n: int = 50,
    max_history_pairs: int = DEFAULT_MAX_HISTORY_PAIRS,
    max_basket_size: int = DEFAULT_MAX_BASKET_SIZE,
) -> List[CoChangePair]:
    """Mine directional co-change rules from the recent change history.

    Returns rules where ``lift >= min_lift`` and the pair has co-occurred
    in at least ``min_pair_support`` deltas. Sorted by lift desc
    (strongest coupling first), then confidence. ``max_history_pairs``
    bounds the input window — see ``_load_deltas_as_transactions``.
    """
    transactions = _load_deltas_as_transactions(
        max_history_pairs=max_history_pairs,
        max_basket_size=max_basket_size,
    )
    total = len(transactions)
    if total == 0:
        return []

    # ── 1. Count per-item and per-pair occurrences in a single pass ──
    item_count: Dict[str, int] = {}
    pair_count: Dict[Tuple[str, str], int] = {}

    for basket in transactions:
        for item in basket:
            item_count[item] = item_count.get(item, 0) + 1
        for a, b in combinations(sorted(basket), 2):
            pair_count[(a, b)] = pair_count.get((a, b), 0) + 1

    # ── 2. Emit both directions (A→B and B→A) — different confidences ──
    results: List[CoChangePair] = []
    for (a, b), co in pair_count.items():
        if co < min_pair_support:
            continue
        occ_a, occ_b = item_count[a], item_count[b]
        support = co / total
        # A → B
        conf_ab = co / occ_a
        lift_ab = conf_ab / (occ_b / total)
        # B → A
        conf_ba = co / occ_b
        lift_ba = conf_ba / (occ_a / total)
        # Both directions share the same lift (symmetric), but we report
        # the more informative direction (higher confidence) only once to
        # keep the list readable.
        if conf_ab >= conf_ba:
            chosen = (a, b, conf_ab, lift_ab, occ_a, occ_b)
        else:
            chosen = (b, a, conf_ba, lift_ba, occ_b, occ_a)
        ao, bo, confidence, lift, oa, ob = chosen

        if lift < min_lift:
            continue

        results.append(CoChangePair(
            object_a=ao,
            object_b=bo,
            co_occurrences=co,
            occurrences_a=oa,
            occurrences_b=ob,
            total_deltas=total,
            support=round(support, 4),
            confidence=round(confidence, 4),
            lift=round(lift, 4),
        ))

    results.sort(key=lambda r: (r.lift, r.confidence), reverse=True)
    return results[:top_n]


def cochange_as_dicts(**kwargs) -> List[Dict]:
    """Convenience wrapper for API/JSON consumers."""
    return [asdict(r) for r in mine_cochange_pairs(**kwargs)]
