"""Declarative base and shared SQLAlchemy metadata configuration."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models in the application."""


# Import ORM model modules so that their mapped classes are registered in
# SQLAlchemy metadata. This is required for runtime table creation and
# application usage and avoids relying on Alembic-specific imports.
import app.db.models.snapshot  # noqa: F401
import app.db.models.schema_snapshot  # noqa: F401
import app.db.models.table_snapshot  # noqa: F401
import app.db.models.column_snapshot  # noqa: F401
# Dict-ingest sub-tables (v1.14.02+). Loaded after table_snapshot so
# their FK target is registered first.
import app.db.models.index_snapshot  # noqa: F401
import app.db.models.partitioning_snapshot  # noqa: F401
import app.db.models.ddl_text_snapshot  # noqa: F401
# Parser-integration tables (introduced in v1.04 for DataDNA parser feed).
# Ordered so Process is loaded before Step (Step has a FK to Process).
import app.db.models.process  # noqa: F401
import app.db.models.step  # noqa: F401
import app.db.models.attribute_lineage  # noqa: F401
import app.diff.diff_models  # noqa: F401
import app.graph.graph_models  # noqa: F401
import app.graph.impact_models  # noqa: F401
import app.taisa.taisa_models  # noqa: F401
import app.usage.usage_models  # noqa: F401
