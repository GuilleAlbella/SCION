"""Unit tests for indirect-lineage support in the column lineage endpoint.

These tests create in-memory attribute_lineage rows and drive the
get_column_lineage endpoint through the FastAPI TestClient so they
exercise the full request/response path without hitting production DB.

What they prove:

1. Rows where target_attribute_natural_key starts with "NOT APPLICABLE"
   are classified as IndirectEdge, not as regular downstream edges.
2. Regular (non-indirect) rows still produce ColumnEdge upstream /
   downstream entries as before.
3. Mixed columns (direct copy + filter predicate) have both edges
   and indirect entries.
4. The response model validates (total_edges counts only direct edges).
5. Indirect list is empty by default on columns with no indirect rows
   (backwards-compatible for callers that ignore the new field).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.attribute_lineage import AttributeLineage
from app.db.models.snapshot import Snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(engine):
    """Build a minimal FastAPI app wired to the supplied engine."""
    from unittest.mock import patch
    from fastapi import FastAPI
    from app.api.v1.lineage import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    # Patch the module-level engine used by the endpoint
    with patch("app.api.v1.lineage.engine", engine):
        yield app


def _seed(session: Session, snapshot_id: int, rows: list[dict]) -> None:
    for r in rows:
        session.add(AttributeLineage(snapshot_id=snapshot_id, **r))
    session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_engine():
    # StaticPool forces SQLAlchemy to reuse one connection — required for
    # in-memory SQLite so that schema created by create_all is visible to
    # all sessions (each new connection would otherwise get an empty DB).
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def snapshot_id(db_engine) -> int:
    with Session(bind=db_engine) as s:
        snap = Snapshot(
            snapshot_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            source_system="TEST",
            description="test snap",
            extract_run_id="run-test-001",
        )
        s.add(snap)
        s.commit()
        return snap.snapshot_id


@pytest.fixture()
def client(db_engine):
    """TestClient with the lineage engine patched to the in-memory DB."""
    from unittest.mock import patch
    from fastapi import FastAPI
    from app.api.v1.lineage import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with patch("app.api.v1.lineage.engine", db_engine):
        yield TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDirectEdgesUnchanged:
    """Direct-copy / aggregate / type-cast rows still produce upstream/downstream."""

    def test_upstream_edge(self, client, db_engine, snapshot_id):
        with Session(bind=db_engine) as s:
            _seed(s, snapshot_id, [
                {
                    "source_attribute_natural_key": "src_schema.src_tbl|col_a",
                    "target_attribute_natural_key": "tgt_schema.tgt_tbl|col_x",
                    "transformation_type": "Direct Copy",
                    "tier": "TIER2",
                }
            ])

        r = client.get(f"/api/v1/lineage/columns?snapshot_id={snapshot_id}&object=tgt_schema.tgt_tbl")
        assert r.status_code == 200
        body = r.json()
        assert body["total_edges"] == 1
        col = body["columns"][0]
        assert col["column_name"] == "col_x"
        assert len(col["upstream"]) == 1
        assert col["upstream"][0]["column_key"] == "src_schema.src_tbl|col_a"
        assert col["upstream"][0]["transformation_type"] == "Direct Copy"
        assert col["indirect"] == []

    def test_downstream_edge(self, client, db_engine, snapshot_id):
        with Session(bind=db_engine) as s:
            _seed(s, snapshot_id, [
                {
                    "source_attribute_natural_key": "src_schema.src_tbl|col_a",
                    "target_attribute_natural_key": "tgt_schema.tgt_tbl|col_x",
                    "transformation_type": "Type Cast",
                    "tier": "TIER2",
                }
            ])

        r = client.get(f"/api/v1/lineage/columns?snapshot_id={snapshot_id}&object=src_schema.src_tbl")
        body = r.json()
        assert body["total_edges"] == 1
        col = body["columns"][0]
        assert col["column_name"] == "col_a"
        assert len(col["downstream"]) == 1
        assert col["downstream"][0]["column_key"] == "tgt_schema.tgt_tbl|col_x"
        assert col["indirect"] == []


class TestIndirectEdges:
    """Rows with target == 'NOT APPLICABLE' go to indirect, not downstream."""

    def test_filter_row_becomes_indirect(self, client, db_engine, snapshot_id):
        with Session(bind=db_engine) as s:
            _seed(s, snapshot_id, [
                {
                    "source_attribute_natural_key": "src_schema.src_tbl|filter_col",
                    "target_attribute_natural_key": "NOT APPLICABLE",
                    "transformation_type": "Filter",
                    "expression": "filter_col = 'ACTIVE'",
                    "tier": "TIER1",
                }
            ])

        r = client.get(f"/api/v1/lineage/columns?snapshot_id={snapshot_id}&object=src_schema.src_tbl")
        body = r.json()
        # Indirect edges are NOT counted in total_edges
        assert body["total_edges"] == 0
        col = body["columns"][0]
        assert col["column_name"] == "filter_col"
        assert col["downstream"] == []
        assert len(col["indirect"]) == 1
        ie = col["indirect"][0]
        assert ie["transformation_type"] == "Filter"
        assert ie["expression"] == "filter_col = 'ACTIVE'"
        assert ie["source_column_name"] == "filter_col"

    def test_join_row_becomes_indirect(self, client, db_engine, snapshot_id):
        with Session(bind=db_engine) as s:
            _seed(s, snapshot_id, [
                {
                    "source_attribute_natural_key": "a_schema.a_tbl|join_key",
                    "target_attribute_natural_key": "NOT APPLICABLE",
                    "transformation_type": "Join",
                    "expression": "a_tbl.join_key = b_tbl.id",
                    "tier": "TIER1",
                }
            ])

        r = client.get(f"/api/v1/lineage/columns?snapshot_id={snapshot_id}&object=a_schema.a_tbl")
        body = r.json()
        col = body["columns"][0]
        assert col["downstream"] == []
        assert col["indirect"][0]["transformation_type"] == "Join"

    def test_not_applicable_prefix_variants(self, client, db_engine, snapshot_id):
        """'NOT APPLICABLE' with any suffix (e.g. 'NOT APPLICABLE.NOT APPLICABLE')
        should also be treated as indirect."""
        with Session(bind=db_engine) as s:
            _seed(s, snapshot_id, [
                {
                    "source_attribute_natural_key": "s.t|col",
                    "target_attribute_natural_key": "NOT APPLICABLE.NOT APPLICABLE|dummy",
                    "transformation_type": "Filter",
                    "tier": "TIER1",
                }
            ])

        r = client.get(f"/api/v1/lineage/columns?snapshot_id={snapshot_id}&object=s.t")
        body = r.json()
        col = body["columns"][0]
        assert col["downstream"] == []
        assert len(col["indirect"]) == 1


class TestMixedColumn:
    """A column with both a direct copy AND a filter predicate."""

    def test_direct_and_indirect_coexist(self, client, db_engine, snapshot_id):
        with Session(bind=db_engine) as s:
            _seed(s, snapshot_id, [
                # Direct lineage row
                {
                    "source_attribute_natural_key": "src.tbl|amount",
                    "target_attribute_natural_key": "tgt.out|raw_amount",
                    "transformation_type": "Direct Copy",
                    "tier": "TIER2",
                },
                # Same column used as a filter
                {
                    "source_attribute_natural_key": "src.tbl|amount",
                    "target_attribute_natural_key": "NOT APPLICABLE",
                    "transformation_type": "Filter",
                    "expression": "amount > 0",
                    "tier": "TIER1",
                },
            ])

        r = client.get(f"/api/v1/lineage/columns?snapshot_id={snapshot_id}&object=src.tbl")
        body = r.json()
        assert body["total_edges"] == 1  # only the direct copy counts
        col = body["columns"][0]
        assert col["column_name"] == "amount"
        assert len(col["downstream"]) == 1
        assert col["downstream"][0]["column_key"] == "tgt.out|raw_amount"
        assert len(col["indirect"]) == 1
        assert col["indirect"][0]["expression"] == "amount > 0"


class TestBackwardsCompatibility:
    """Existing callers must not break: indirect defaults to []."""

    def test_indirect_field_present_even_when_empty(self, client, db_engine, snapshot_id):
        with Session(bind=db_engine) as s:
            _seed(s, snapshot_id, [
                {
                    "source_attribute_natural_key": "a.b|c",
                    "target_attribute_natural_key": "x.y|z",
                    "transformation_type": "Aggregate",
                    "tier": "TIER2",
                }
            ])

        r = client.get(f"/api/v1/lineage/columns?snapshot_id={snapshot_id}&object=a.b")
        body = r.json()
        col = body["columns"][0]
        assert "indirect" in col
        assert col["indirect"] == []


class TestStepNaturalKey:
    """step_natural_key is exposed in ColumnEdge (Feature 3)."""

    def test_step_key_propagated_when_present(self, client, db_engine, snapshot_id):
        with Session(bind=db_engine) as s:
            _seed(s, snapshot_id, [
                {
                    "source_attribute_natural_key": "src.tbl|col_a",
                    "target_attribute_natural_key": "tgt.tbl|col_b",
                    "transformation_type": "Direct Copy",
                    "tier": "TIER2",
                    "step_natural_key": "STEP.ETL.001",
                }
            ])

        r = client.get(f"/api/v1/lineage/columns?snapshot_id={snapshot_id}&object=src.tbl")
        body = r.json()
        col = body["columns"][0]
        assert col["downstream"][0]["step_natural_key"] == "STEP.ETL.001"

    def test_step_key_null_when_absent(self, client, db_engine, snapshot_id):
        with Session(bind=db_engine) as s:
            _seed(s, snapshot_id, [
                {
                    "source_attribute_natural_key": "src.tbl|col_a",
                    "target_attribute_natural_key": "tgt.tbl|col_b",
                    "transformation_type": "Aggregate",
                    "tier": "TIER2",
                }
            ])

        r = client.get(f"/api/v1/lineage/columns?snapshot_id={snapshot_id}&object=src.tbl")
        body = r.json()
        col = body["columns"][0]
        assert col["downstream"][0]["step_natural_key"] is None

    def test_step_key_on_upstream_edge(self, client, db_engine, snapshot_id):
        """step_natural_key also flows through the upstream ColumnEdge."""
        with Session(bind=db_engine) as s:
            _seed(s, snapshot_id, [
                {
                    "source_attribute_natural_key": "src.tbl|col_x",
                    "target_attribute_natural_key": "tgt.tbl|col_y",
                    "transformation_type": "Type Cast",
                    "tier": "TIER2",
                    "step_natural_key": "STEP.ETL.002",
                }
            ])

        r = client.get(f"/api/v1/lineage/columns?snapshot_id={snapshot_id}&object=tgt.tbl")
        body = r.json()
        col = body["columns"][0]
        assert col["upstream"][0]["step_natural_key"] == "STEP.ETL.002"
