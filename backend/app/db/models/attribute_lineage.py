"""SQLAlchemy model for column-level lineage (Tier 1 / Tier 2 from the parser).

While the classic `graph_edge` table captures dataset-to-dataset dependencies
(Tier 3 lineage), this table captures the FINER-GRAINED column-to-column
lineage that the parser also emits:

- Tier 1: query-block level (per SELECT / subquery)
- Tier 2: statement level (per INSERT / CREATE TABLE AS ...)
- lineageFactAttribute: the consolidated fact table from the parser

One row per (source_attribute, target_attribute, step). Includes the
parser's `expression` (the SQL fragment that produced the mapping) and
`transformationType` (Direct Copy / Filter / Aggregate / ...), both of
which are gold for TAISA's Q&A context.

Introduced in SCION v1.04. Populated only for Tier 1/2 edges; Tier 3
continues to live in `graph_edge` for graph-algorithm compatibility.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AttributeLineage(Base):
    """A column-to-column lineage edge derived from parser Tier 1/Tier 2 data.

    Keys are stored as natural-key strings (not FKs) because the parser's
    attribute catalog may legitimately contain entries we chose to filter out
    as noise; storing the raw identifier keeps the row self-describing and
    avoids orphaning if downstream filtering changes.

    Attributes:
        lineage_id: Surrogate key.
        snapshot_id: SCION snapshot this edge belongs to.
        source_attribute_natural_key: Origin column (e.g.
            ``"DBC.BAR_DATABASES2V|DATABASEID"``).
        source_dataset_natural_key: The origin table/view.
        target_attribute_natural_key: Destination column.
        target_dataset_natural_key: The destination table/view.
        step_natural_key: Which step in which process produced this mapping.
        tier: ``"TIER1"`` (query block) or ``"TIER2"`` (statement).
        expression: The SQL fragment that realises the mapping — powers
            TAISA explanations (e.g. "populated by COALESCE(x, y)").
        transformation_type: Parser classification: ``"Direct Copy"``,
            ``"Filter"``, ``"Aggregate"``, etc.
        parse_run_id: Correlates with the parser run.
        parse_timestamp: Original parse moment.
        created_at: Ingestion moment.
    """

    __tablename__ = "attribute_lineage"

    lineage_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("snapshot.snapshot_id"), nullable=False
    )
    source_attribute_natural_key: Mapped[str] = mapped_column(String, nullable=False)
    source_dataset_natural_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_attribute_natural_key: Mapped[str] = mapped_column(String, nullable=False)
    target_dataset_natural_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    step_natural_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tier: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # `expression` uses TEXT because some parser-generated expressions are
    # multi-kilobyte (e.g. long IN clauses with hundreds of literals).
    expression: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    transformation_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    parse_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    parse_timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # Composite indexes that mirror the upstream/downstream lineage walks:
    # the lineage browser starts from either side of the edge and walks
    # within a single snapshot, so each query filters by
    # ``(snapshot_id, attribute_natural_key)``. Created in alembic
    # f1a8b3c5d207 — declared here so ``Base.metadata.create_all`` (used
    # by tests and fresh-DB bootstrapping) produces an identical schema.
    __table_args__ = (
        Index(
            "ix_attr_lineage_source",
            "snapshot_id",
            "source_attribute_natural_key",
        ),
        Index(
            "ix_attr_lineage_target",
            "snapshot_id",
            "target_attribute_natural_key",
        ),
    )
