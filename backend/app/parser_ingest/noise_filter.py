"""Heuristic noise filter for parser v1 payloads.

The parser v1 emits a few placeholder entities for cases where it can't
resolve a reference (e.g. the target of an INSERT whose dataset name was
ambiguous in the SQL). It also models SQL LITERALS (e.g. `'D'`, `NULL`,
`'000000000000'`) as attributes inside a pseudo-dataset.

These add noise to SCION's Graph and Lineage views because they appear
as first-class objects alongside real tables and columns. Until the
parser team adds an explicit `attributeClass` / `datasetClass` field
(asked in the review email), we classify via string heuristics.

When the parser adds the classifier, this module becomes a one-line
change (`return attr.attribute_class != "column"`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

from .parser_models import (
    ParsedAttribute,
    ParsedAttributeLineage,
    ParsedContainer,
    ParsedDataset,
    ParsedDatasetLineage,
    ParsedLineagePayload,
)


# ──── Heuristic rules (string-level) ────
# All lowercase-compared via _norm() to be case-insensitive.

# Containers / datasets that are parser placeholders.
_PLACEHOLDER_CONTAINERS = {"not applicable", "unknown"}

# Dataset prefixes that indicate synthetic temp tables.
_TEMP_DATASET_PATTERNS = (
    re.compile(r"^unknown\.temptable\d+$", re.IGNORECASE),
    re.compile(r"^.*\.tmp_\w+$",             re.IGNORECASE),  # *.tmp_xxx
)

# Attribute natural keys for SQL literals — parser encodes them like
# "NOT APPLICABLE.NOT APPLICABLE|'D'" or "|NULL" or "|'000000000000'".
_LITERAL_ATTR_PATTERNS = (
    re.compile(r"\|'[^']*'$"),      # |'D', |'abc', |'12345'
    re.compile(r"\|NULL$",  re.IGNORECASE),
    re.compile(r"\|\d+$"),           # |123 (bare number literal)
    re.compile(r"\|NOT[_ ]APPLICABLE"),
)


def _norm(s: str) -> str:
    """Lowercase and strip — the canonical form we compare against."""
    return (s or "").strip().lower()


def _is_placeholder_container(natural_key: str) -> bool:
    """True for parser-emitted placeholder containers (NOT APPLICABLE, UNKNOWN)."""
    return _norm(natural_key) in _PLACEHOLDER_CONTAINERS


def _is_placeholder_dataset(natural_key: str, container_key: str) -> bool:
    """True when the dataset is either in a placeholder container OR matches
    a temp-table pattern. We classify temp tables as noise at the schema
    level — their lineage is still captured because step info carries the
    actual statement that created them."""
    if _is_placeholder_container(container_key):
        return True
    for pat in _TEMP_DATASET_PATTERNS:
        if pat.match(natural_key or ""):
            return True
    return False


def _is_literal_attribute(attr: ParsedAttribute) -> bool:
    """True when the attribute represents a SQL literal, not a real column."""
    # If the parser already classified it, trust that (future v2 case).
    if attr.attribute_class:
        return attr.attribute_class.lower() != "column"
    # Fall back to string heuristics on the natural key.
    key = attr.attribute_natural_key or ""
    for pat in _LITERAL_ATTR_PATTERNS:
        if pat.search(key):
            return True
    # Also discard attributes that live on a placeholder dataset.
    if _is_placeholder_container(attr.container_natural_key):
        return True
    return False


@dataclass
class NoiseFilterStats:
    """Counts of what was kept vs dropped. Surfaced in the IngestionReport."""
    kept_containers: int = 0
    dropped_containers: int = 0
    kept_datasets: int = 0
    dropped_datasets: int = 0
    kept_attributes: int = 0
    dropped_attributes_literal: int = 0
    dropped_attributes_placeholder: int = 0
    kept_dataset_lineage: int = 0
    dropped_dataset_lineage: int = 0
    kept_attribute_lineage: int = 0
    dropped_attribute_lineage: int = 0
    # Samples of what was dropped — useful for QA / debugging. Capped per
    # category to avoid ballooning the response.
    dropped_samples: Dict[str, List[str]] = field(default_factory=dict)


def _add_sample(stats: NoiseFilterStats, category: str, value: str, limit: int = 10) -> None:
    """Collect a bounded sample of dropped values for the audit report."""
    bucket = stats.dropped_samples.setdefault(category, [])
    if len(bucket) < limit:
        bucket.append(value)


def apply(payload: ParsedLineagePayload) -> NoiseFilterStats:
    """Drop placeholder / literal entities from `payload` in-place.

    After this runs, `payload` contains only real databases, real tables,
    real columns, and edges whose endpoints survived the filter.

    Args:
        payload: The parsed payload. Mutated in place for memory efficiency —
            a fresh copy would double memory for large production loads.

    Returns:
        `NoiseFilterStats` with kept/dropped counts plus samples of what
        was removed (for the ingestion report).
    """
    stats = NoiseFilterStats()

    # ──── 1. Containers ────
    # Placeholder containers are kept in the payload as-is (so lineage
    # edges that reference them can still be flagged), but we track them
    # separately so downstream can drop edges that point to them.
    kept_containers: List[ParsedContainer] = []
    placeholder_container_keys: set[str] = set()
    for c in payload.containers:
        if _is_placeholder_container(c.container_natural_key):
            placeholder_container_keys.add(c.container_natural_key)
            stats.dropped_containers += 1
            _add_sample(stats, "containers", c.container_natural_key)
        else:
            kept_containers.append(c)
            stats.kept_containers += 1
    payload.containers = kept_containers

    # ──── 2. Datasets ────
    # Any dataset in a placeholder container, OR matching a temp pattern.
    kept_datasets: List[ParsedDataset] = []
    dropped_dataset_keys: set[str] = set()
    for d in payload.datasets:
        if _is_placeholder_dataset(d.dataset_natural_key, d.container_natural_key):
            dropped_dataset_keys.add(d.dataset_natural_key)
            stats.dropped_datasets += 1
            _add_sample(stats, "datasets", d.dataset_natural_key)
        else:
            kept_datasets.append(d)
            stats.kept_datasets += 1
    payload.datasets = kept_datasets

    # ──── 3. Attributes ────
    # Split reasons so we can tell users how much was literals vs
    # placeholder-on-a-dropped-dataset.
    kept_attributes: List[ParsedAttribute] = []
    dropped_attribute_keys: set[str] = set()
    for a in payload.attributes:
        if _is_literal_attribute(a):
            dropped_attribute_keys.add(a.attribute_natural_key)
            stats.dropped_attributes_literal += 1
            _add_sample(stats, "attributes_literal", a.attribute_natural_key)
        elif a.dataset_natural_key in dropped_dataset_keys:
            dropped_attribute_keys.add(a.attribute_natural_key)
            stats.dropped_attributes_placeholder += 1
            _add_sample(stats, "attributes_placeholder", a.attribute_natural_key)
        else:
            kept_attributes.append(a)
            stats.kept_attributes += 1
    payload.attributes = kept_attributes

    # ──── 4. Dataset lineage edges ────
    # Drop an edge if either endpoint (source or target dataset) was filtered.
    # Also drop self-loop edges (source == target) — they are parser artefacts
    # from queries that read and write the same table (e.g. INSERT INTO T
    # SELECT … FROM T). Self-loops carry no actionable lineage information
    # and break the dagre layout on the frontend.
    # This preserves graph integrity — no edges to nodes that don't exist.
    kept_ds_edges: List[ParsedDatasetLineage] = []
    for e in payload.dataset_lineage:
        if e.source_dataset_natural_key in dropped_dataset_keys or \
           e.target_dataset_natural_key in dropped_dataset_keys:
            stats.dropped_dataset_lineage += 1
        elif e.source_dataset_natural_key == e.target_dataset_natural_key:
            # Self-loop: same object on both sides — drop silently.
            stats.dropped_dataset_lineage += 1
            _add_sample(stats, "dataset_lineage_self_loop", e.source_dataset_natural_key)
        else:
            kept_ds_edges.append(e)
            stats.kept_dataset_lineage += 1
    payload.dataset_lineage = kept_ds_edges

    # ──── 5. Attribute lineage edges ────
    # Same rule — drop if either attribute endpoint was classified as noise.
    kept_attr_edges: List[ParsedAttributeLineage] = []
    for e in payload.attribute_lineage:
        if e.source_attribute_natural_key in dropped_attribute_keys or \
           e.target_attribute_natural_key in dropped_attribute_keys:
            stats.dropped_attribute_lineage += 1
        else:
            kept_attr_edges.append(e)
            stats.kept_attribute_lineage += 1
    payload.attribute_lineage = kept_attr_edges

    # Store on the payload so later stages can read it without re-filtering.
    payload.stats["noise_filter"] = {
        "kept_containers": stats.kept_containers,
        "dropped_containers": stats.dropped_containers,
        "kept_datasets": stats.kept_datasets,
        "dropped_datasets": stats.dropped_datasets,
        "kept_attributes": stats.kept_attributes,
        "dropped_attributes_literal": stats.dropped_attributes_literal,
        "dropped_attributes_placeholder": stats.dropped_attributes_placeholder,
        "kept_dataset_lineage": stats.kept_dataset_lineage,
        "dropped_dataset_lineage": stats.dropped_dataset_lineage,
        "kept_attribute_lineage": stats.kept_attribute_lineage,
        "dropped_attribute_lineage": stats.dropped_attribute_lineage,
    }

    return stats
