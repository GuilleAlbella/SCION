import pytest
from datetime import UTC, datetime
from sqlalchemy.orm import Session, sessionmaker

from app.snapshot.control.snapshot_policy import SnapshotPolicy
from app.snapshot.control.execution_guard import SnapshotExecutionGuard
from app.db.models.snapshot import Snapshot
from app.db.engine import engine
from app.db.base import Base


def _reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_baseline_duplicate_is_blocked():
    _reset_db()

    SessionLocal = sessionmaker(bind=engine)
    session: Session = SessionLocal()
    try:
        session.add(
            Snapshot(
                snapshot_time=datetime.now(UTC),
                source_system="demo",
                description="Initial baseline",
                is_baseline=True,
            )
        )
        session.commit()

        policy = SnapshotPolicy()
        guard = SnapshotExecutionGuard(session, policy)

        with pytest.raises(RuntimeError):
            guard.assert_can_execute(
                source_system="demo",
                description="Another baseline",
                is_baseline=True,
            )
    finally:
        session.close()


def test_duplicate_description_blocked():
    _reset_db()

    SessionLocal = sessionmaker(bind=engine)
    session: Session = SessionLocal()
    try:
        session.add(
            Snapshot(
                snapshot_time=datetime.now(UTC),
                source_system="demo",
                description="Daily snapshot",
                is_baseline=False,
            )
        )
        session.commit()

        policy = SnapshotPolicy(allow_duplicate_descriptions=False)
        guard = SnapshotExecutionGuard(session, policy)

        with pytest.raises(RuntimeError):
            guard.assert_can_execute(
                source_system="demo",
                description="Daily snapshot",
                is_baseline=False,
            )
    finally:
        session.close()


def test_snapshot_allowed_when_policy_allows():
    _reset_db()

    SessionLocal = sessionmaker(bind=engine)
    session: Session = SessionLocal()
    try:
        policy = SnapshotPolicy()
        guard = SnapshotExecutionGuard(session, policy)

        guard.assert_can_execute(
            source_system="demo",
            description="First snapshot",
            is_baseline=False,
        )
    finally:
        session.close()
