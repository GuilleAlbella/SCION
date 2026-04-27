"""Internal dataclasses representing the parsed parser payload.

These are SCION-internal types that decouple the ingestion pipeline from
the exact JSON shape coming from the parser. If the parser changes field
names in v2, only `teradata_parser.parse()` needs updating — everything
downstream consumes these dataclasses.

Design notes:
- All identifiers use the parser's `naturalKey` strings (stable across runs).
- `rawJson` is preserved on each entity for audit and re-ingestion.
- Missing fields (e.g. `datasetType`, `dataType` — not in parser v1) are
  typed as Optional with default ``None`` so future parser versions can
  populate them without breaking v1 ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ParsedPlatform:
    """Top-level platform block: one per parse run."""
    platform_natural_key: str
    technology: Optional[str] = None


@dataclass
class ParsedContainer:
    """A container — maps to SCION's schema_snapshot (i.e. a database)."""
    container_natural_key: str
    platform_natural_key: str
    technology: Optional[str] = None


@dataclass
class ParsedDataset:
    """A dataset (table / view / ... in the parser's vocabulary)."""
    dataset_natural_key: str           # e.g. "DBC.BAR_DATABASES2V"
    container_natural_key: str
    platform_natural_key: str
    technology: Optional[str] = None
    # Phase 2 field — not present in parser v1. Defaults to None so downstream
    # code can fall back to "UNKNOWN" and advance through the pipeline.
    dataset_type: Optional[str] = None  # TABLE | VIEW | STORED_PROCEDURE | ...


@dataclass
class ParsedAttribute:
    """An attribute — maps to column_snapshot when it's a real column."""
    attribute_natural_key: str         # e.g. "DBC.BAR_DATABASES2V|DATABASEID"
    dataset_natural_key: str
    container_natural_key: str
    platform_natural_key: str
    technology: Optional[str] = None
    # Phase 2 fields — populated when the parser gets extended.
    data_type: Optional[str] = None
    nullable: Optional[bool] = None
    ordinal_position: Optional[int] = None
    # v1 puts literals and unresolved refs into this array too. We classify
    # here (via noise_filter) so the ingestor can skip literals/temps cleanly.
    attribute_class: Optional[str] = None  # "column" | "literal" | "unresolved" | "temp"


@dataclass
class ParsedProcessGroup:
    """Upstream grouping of processes — e.g. all DBQL-derived scripts."""
    process_group_natural_key: str
    platform_natural_key: str


@dataclass
class ParsedProcess:
    """A SQL script / job / stored procedure captured by the parser."""
    process_natural_key: str
    process_type: Optional[str] = None
    process_group_natural_key: Optional[str] = None
    platform_natural_key: Optional[str] = None


@dataclass
class ParsedStep:
    """A statement or query block within a process."""
    step_natural_key: str
    process_natural_key: str
    step_level: Optional[str] = None   # STATEMENT | QUERY_BLOCK
    step_type: Optional[str] = None    # INSERT, SELECT, CREATE_TABLE, ...
    parent_step_natural_key: Optional[str] = None
    process_group_natural_key: Optional[str] = None
    platform_natural_key: Optional[str] = None


@dataclass
class ParsedDatasetLineage:
    """Tier-3 edge: dataset → dataset (maps directly to graph_edge in SCION)."""
    source_dataset_natural_key: str
    target_dataset_natural_key: str
    source_container_natural_key: Optional[str] = None
    source_platform_natural_key: Optional[str] = None
    target_container_natural_key: Optional[str] = None
    target_platform_natural_key: Optional[str] = None
    step_natural_key: Optional[str] = None
    impact_type: Optional[str] = None  # "Direct" | "Indirect"


@dataclass
class ParsedAttributeLineage:
    """Tier-1 or Tier-2 edge: attribute → attribute."""
    source_attribute_natural_key: str
    target_attribute_natural_key: str
    tier: str  # "TIER1" | "TIER2"
    source_dataset_natural_key: Optional[str] = None
    target_dataset_natural_key: Optional[str] = None
    step_natural_key: Optional[str] = None
    expression: Optional[str] = None
    transformation_type: Optional[str] = None


@dataclass
class ParsedLineagePayload:
    """The complete, validated parser feed, ready for ingestion.

    This is what the ingestor consumes. It's produced by
    `teradata_parser.parse()` and optionally cleaned by `noise_filter.apply()`.

    Attributes:
        parse_run_id: Stable identifier for the parser run (UUID from the
            parser). Used by SCION to correlate back to the source.
        parse_timestamp: When the parser extracted this payload. We use it
            as the snapshot timestamp in SCION.
        platform: Top-level platform info.
        containers: Databases found by the parser.
        datasets: Tables/views.
        attributes: Columns (and noise like literals — filtered later).
        process_groups: Script groupings.
        processes: Individual scripts/jobs.
        steps: Statements / query blocks inside processes.
        dataset_lineage: Tier-3 edges (→ graph_edge).
        attribute_lineage: Tier-1/Tier-2 edges (→ attribute_lineage).
    """

    parse_run_id: str
    parse_timestamp: datetime
    platform: ParsedPlatform
    containers: List[ParsedContainer] = field(default_factory=list)
    datasets: List[ParsedDataset] = field(default_factory=list)
    attributes: List[ParsedAttribute] = field(default_factory=list)
    process_groups: List[ParsedProcessGroup] = field(default_factory=list)
    processes: List[ParsedProcess] = field(default_factory=list)
    steps: List[ParsedStep] = field(default_factory=list)
    dataset_lineage: List[ParsedDatasetLineage] = field(default_factory=list)
    attribute_lineage: List[ParsedAttributeLineage] = field(default_factory=list)

    # Stats populated incrementally by each stage in the pipeline.
    stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestionReport:
    """Result of an ingestion run (either real or dry-run).

    Every downstream caller (API, CLI, test) gets the same structured
    summary so the UI can render rich feedback.
    """

    dry_run: bool
    snapshot_id: Optional[int]  # None when dry_run
    parse_run_id: str
    parse_timestamp: datetime
    # Input stats (what came from the parser).
    input_counts: Dict[str, int] = field(default_factory=dict)
    # Filter stats (how much noise was dropped).
    filtered_counts: Dict[str, int] = field(default_factory=dict)
    # Persistence stats (what ended up in SCION).
    persisted_counts: Dict[str, int] = field(default_factory=dict)
    # Non-fatal issues surfaced during ingestion (missing parent, unknown
    # type, etc). Free-form strings; shown to the user for review.
    warnings: List[str] = field(default_factory=list)
