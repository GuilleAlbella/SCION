from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from datetime import datetime


class GraphNode(Base):
    """ORM model representing a node in the dependency graph.

    Nodes are created exclusively during snapshot execution and represent
    structural objects (tables, columns, etc.) for a specific snapshot.
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


class GraphEdge(Base):
    """ORM model representing a directed edge between graph nodes.

    v0: structural definition only, no behaviour or relationships.
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
