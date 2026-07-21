"""ORM models for §2.10 Reference Data.

Three hierarchies stored here:
  1. Org hierarchy  — DepartmentEntity → TeamEntity → UserEntity
  2. Business apps  — ApplicationEntity + mapping tables

UserEntity.username is the join key against UsageEvent.username
(populated once the PDCR extractor provides per-user rows).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DepartmentEntity(Base):
    """Top-level organisational unit (LOB / department)."""

    __tablename__ = "department_entity"

    department_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    department_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    teams: Mapped[list["TeamEntity"]] = relationship(back_populates="department")


class TeamEntity(Base):
    """Team within a department."""

    __tablename__ = "team_entity"

    team_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    department_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("department_entity.department_id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    department: Mapped[Optional["DepartmentEntity"]] = relationship(back_populates="teams")
    users: Mapped[list["UserEntity"]] = relationship(back_populates="team")
    applications: Mapped[list["ApplicationEntity"]] = relationship(back_populates="owner_team")


class UserEntity(Base):
    """Individual database user; join key with usage_event.username."""

    __tablename__ = "user_entity"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    team_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("team_entity.team_id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    team: Mapped[Optional["TeamEntity"]] = relationship(back_populates="users")


class ApplicationEntity(Base):
    """Business application that owns or uses database objects."""

    __tablename__ = "application_entity"

    application_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_team_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("team_entity.team_id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    owner_team: Mapped[Optional["TeamEntity"]] = relationship(back_populates="applications")
    schema_mappings: Mapped[list["DatabaseApplicationMapping"]] = relationship(
        back_populates="application"
    )
    table_mappings: Mapped[list["TableApplicationMapping"]] = relationship(
        back_populates="application"
    )


class DatabaseApplicationMapping(Base):
    """Maps a schema/database name to a business application."""

    __tablename__ = "database_application_mapping"
    __table_args__ = (UniqueConstraint("schema_name", "application_id", name="uq_db_app"),)

    mapping_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schema_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    application_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("application_entity.application_id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    application: Mapped["ApplicationEntity"] = relationship(back_populates="schema_mappings")


class TableApplicationMapping(Base):
    """Maps a specific table to a business application."""

    __tablename__ = "table_application_mapping"
    __table_args__ = (
        UniqueConstraint("schema_name", "table_name", "application_id", name="uq_table_app"),
    )

    mapping_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schema_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    table_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    application_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("application_entity.application_id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    application: Mapped["ApplicationEntity"] = relationship(back_populates="table_mappings")
