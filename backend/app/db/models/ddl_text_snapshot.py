"""SQLAlchemy model for the assembled DDL text of an object."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DDLTextSnapshot(Base):
    """The full reconstructed CREATE statement for a table/view/proc.

    Source: `DBC.TableTextV` chunks the `RequestText` of each object
    into multiple rows ordered by `LineNo`. The dict-import pipeline
    runs `assemble_ddl()` to concatenate them in order, then stores
    the result here as a single row per object.

    Why a single row (not per-fragment): every consumer (DDL Generator,
    TAISA context builder, future code-diff UI) wants the whole DDL
    at once. Storing fragments would require a join on every read.
    `request_text_fragments` keeps the original chunk count for
    diagnostics — useful when reasoning about edge cases later.

    Cascades on delete via `table_snapshot` FK. Unique on `table_id`
    so re-imports overwrite cleanly.
    """

    __tablename__ = "ddl_text_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("table_snapshot.table_id"),
        nullable=False,
        unique=True,
    )
    ddl_text: Mapped[str] = mapped_column(Text, nullable=False)
    request_text_fragments: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
