from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy import DateTime, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from datetime import datetime


class GraphNode(Base):
    """ORM model representing a node in the dependency graph.

    Nodes are created exclusively during snapshot execution and represent
    structural objects (tables, columns, etc.) for a specific snapshot.

    Indexes (alembic d05a1b2c3d4e):

    - ``ix_graph_node_snapshot``: every graph fetch / lineage subgraph /
      criticality computation filters by ``snapshot_id``. With 337k nodes
      on a Transcend extract this is the difference between an instant
      response and a full-table scan.
    - ``ix_graph_node_search``: composite over
      ``(snapshot_id, schema_name, object_name)`` to back the
      ``/objects/search?source=graph`` autocomplete with a single index seek.
    """

    __tablename__ = "graph_node"

    node_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    object_type: Mapped[str] = mapped_column(String, nullable=False)
    object_name: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_id: Mapped[int] = mapped_column(Integer, nullable=False)
    node_metadata: Mapped[Optional[Dict]] = mapped_column("metadata", JSON, nullable=True)
    schema_name: Mapped[str] = mapped_column(String, nullable=False)
    node_uid: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_graph_node_snapshot", "snapshot_id"),
        Index("ix_graph_node_search", "snapshot_id", "schema_name", "object_name"),
    )


class GraphEdge(Base):
    """ORM model representing a directed edge between graph nodes.

    v0: structural definition only, no behaviour or relationships.

    Indexes:
    - ``ix_graph_edge_snapshot`` on ``snapshot_id`` so edge fetches for a
      snapshot don't scan the whole table.
    - ``ix_graph_edge_snapshot_source`` / ``ix_graph_edge_snapshot_target``
      support recursive impact walks, which always constrain by snapshot and
      then expand from either source_node_id or target_node_id.
    """

    __tablename__ = "graph_edge"

    edge_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # Existing columns (do not modify semantics)
    source_node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    target_node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    relationship_type: Mapped[str] = mapped_column(String, nullable=False)

    # New, optional columns used by the System Graph API.
    from_node_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    to_node_uid: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    edge_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    edge_metadata: Mapped[Optional[Dict]] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=True,
    )

    __table_args__ = (
        Index("ix_graph_edge_snapshot", "snapshot_id"),
        Index("ix_graph_edge_snapshot_source", "snapshot_id", "source_node_id"),
        Index("ix_graph_edge_snapshot_target", "snapshot_id", "target_node_id"),
    )
