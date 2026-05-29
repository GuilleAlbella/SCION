"""Pure-unit tests for the dict-import endpoint's routing helpers.

The full-endpoint TestClient tests in this directory are skipped
(see conftest.py — known broken pending test-isolation work). The
routing logic added in Pipeline 3 PR-D is pure, so we test it
without spinning up the FastAPI app or hitting the DB. End-to-end
verification happens via the real-Transcend extract upload.

What this file proves:

  1. ``_content_type_to_category`` now maps both content-type
     enums to the right bucket names — dict views to their existing
     categories, PDCR files to ``dbql_log`` / ``object_usage``.
  2. ``_DICT_CATEGORIES`` and ``_PDCR_CATEGORIES`` partition every
     supported category exactly once — no accidental overlap that
     would let a PDCR file get fed to the dict pipeline.
  3. The new ``DictImportResponse`` fields all default to zero / empty
     so old clients that ignore them keep working.
"""

# The endpoint module is pure-Python at import time (FastAPI is only
# touched at decorator level). We import the private helpers
# directly — they're stable enough to test by name.
import pytest

from app.api.v1.dict_import import (
    DictImportResponse,
    _DICT_CATEGORIES,
    _PDCR_CATEGORIES,
    _content_type_to_category,
)
from app.metadata.format_detector import ContentType

# The conftest skip-mark applies to every test in this dir; opt back
# in here — these tests don't depend on seeded DB state.
pytestmark = []


# ──── _content_type_to_category ────


def test_dict_content_types_map_to_existing_categories():
    """Every DICT_* enum still routes to the bucket it always has.

    Regression guard for PR-D: adding the PDCR mappings must not
    perturb the dict mapping, otherwise existing uploads break.
    """
    assert _content_type_to_category(ContentType.DICT_DATABASES) == "databases"
    assert _content_type_to_category(ContentType.DICT_TABLES) == "tables"
    assert _content_type_to_category(ContentType.DICT_COLUMNS) == "columns"
    assert _content_type_to_category(ContentType.DICT_INDICES) == "indices"
    assert _content_type_to_category(ContentType.DICT_PARTITIONING) == "partitioning"
    assert _content_type_to_category(ContentType.DICT_TABLETEXT) == "tabletext"


def test_pdcr_content_types_map_to_pdcr_categories():
    """PDCR enums route to the dedicated PDCR buckets (PR-D)."""
    assert _content_type_to_category(ContentType.USAGE_DBQL) == "dbql_log"
    assert _content_type_to_category(ContentType.USAGE_OBJECT) == "object_usage"


def test_unknown_content_type_returns_none():
    """A content type the endpoint doesn't accept stays unmapped.

    The handler treats ``None`` as a clean 400 trigger. UNKNOWN is
    the canonical example; if any future enum value isn't routed
    here, it'll fall through this branch.
    """
    assert _content_type_to_category(ContentType.UNKNOWN) is None


# ──── Partition tables ────


def test_dict_and_pdcr_categories_dont_overlap():
    """The two partition sets must be disjoint.

    If a category landed in both, the handler would route it to
    *one* pipeline (dict wins because that branch is checked
    first), silently ignoring the PDCR file. Explicit guard.
    """
    assert _DICT_CATEGORIES.isdisjoint(_PDCR_CATEGORIES)


def test_every_mapped_category_is_in_exactly_one_partition():
    """Every value emitted by `_content_type_to_category` is routable.

    If a future content type maps to a category that's in neither
    partition table, the handler would persist the temp file but
    never feed it to any pipeline — a silent data-loss class of
    bug. This test catches that at PR review time.
    """
    mapped = set()
    for ct in ContentType:
        cat = _content_type_to_category(ct)
        if cat is not None:
            mapped.add(cat)
    union = _DICT_CATEGORIES | _PDCR_CATEGORIES
    assert mapped == union, (
        f"Categories emitted by mapping but not in any partition: "
        f"{mapped - union}. Categories in a partition but never "
        f"emitted by the mapping: {union - mapped}."
    )


# ──── Response shape ────


def test_response_pdcr_fields_default_to_zero():
    """Dict-only callers see zeroed PDCR counts, never None.

    Frontends rendering the counters directly into JSX must not
    have to None-check every field; defaulting to 0 keeps the
    response shape stable across dict-only and mixed batches.
    """
    r = DictImportResponse(
        snapshot_id=1,
        skipped_existing=False,
        source_system_name="x",
        extract_run_id="y",
        schemas_created=0,
        tables_created=0,
        columns_created=0,
        indices_created=0,
        partitioning_created=0,
        ddl_text_created=0,
        indices_seen=0,
        partitioning_seen=0,
        tabletext_seen=0,
        files_received=6,
    )
    assert r.dbql_inserted == 0
    assert r.dbql_skipped_duplicate == 0
    assert r.dbql_skipped_invalid == 0
    assert r.object_usage_inserted == 0
    assert r.object_usage_skipped_unmapped_type == 0
    assert r.object_usage_skipped_orphan == 0
    assert r.object_usage_skipped_invalid == 0
    assert r.object_usage_skipped_by_type == {}
    assert r.pdcr_resolved_against_snapshot_id is None
    # PR-E criticality re-compute fields default to "not run".
    assert r.criticality_recomputed is False
    assert r.criticality_high_count == 0
    assert r.criticality_medium_count == 0
    assert r.criticality_low_count == 0


def test_response_criticality_recompute_fields_round_trip():
    """PR-E criticality fields populate and survive round-trip.

    The handler sets these after re-running ``compute_criticality``
    with ``usage_available=True``. The frontend reads them straight
    out of the response to update the Criticality KPI cards without
    having to re-fetch ``/usage/criticality``.
    """
    r = DictImportResponse(
        snapshot_id=1,
        skipped_existing=False,
        source_system_name="x",
        extract_run_id="y",
        schemas_created=0, tables_created=0, columns_created=0,
        indices_created=0, partitioning_created=0, ddl_text_created=0,
        indices_seen=0, partitioning_seen=0, tabletext_seen=0,
        files_received=8,
        criticality_recomputed=True,
        criticality_high_count=120,
        criticality_medium_count=4500,
        criticality_low_count=235_000,
    )
    rebuilt = DictImportResponse(**r.model_dump())
    assert rebuilt.criticality_recomputed is True
    assert rebuilt.criticality_high_count == 120
    assert rebuilt.criticality_medium_count == 4500
    assert rebuilt.criticality_low_count == 235_000


def test_response_pdcr_fields_round_trip():
    """Populated PDCR fields survive Pydantic model round-tripping.

    Pydantic v2 changes how default-factory dicts behave; this
    catches the case where `skipped_by_type` accidentally becomes
    a class-level mutable shared across instances.
    """
    r1 = DictImportResponse(
        snapshot_id=1,
        skipped_existing=False,
        source_system_name="x",
        extract_run_id="y",
        schemas_created=0, tables_created=0, columns_created=0,
        indices_created=0, partitioning_created=0, ddl_text_created=0,
        indices_seen=0, partitioning_seen=0, tabletext_seen=0,
        files_received=8,
        dbql_inserted=42,
        object_usage_inserted=100,
        object_usage_skipped_by_type={"UDF": 5, "SP": 2},
        pdcr_resolved_against_snapshot_id=7,
    )
    r2 = DictImportResponse(
        snapshot_id=2,
        skipped_existing=False,
        source_system_name="x",
        extract_run_id="z",
        schemas_created=0, tables_created=0, columns_created=0,
        indices_created=0, partitioning_created=0, ddl_text_created=0,
        indices_seen=0, partitioning_seen=0, tabletext_seen=0,
        files_received=6,
    )
    # r1's populated dict must not leak into r2's default.
    assert r2.object_usage_skipped_by_type == {}
    # r1 round-trips through model_dump → re-construction unchanged.
    rebuilt = DictImportResponse(**r1.model_dump())
    assert rebuilt.dbql_inserted == 42
    assert rebuilt.object_usage_skipped_by_type == {"UDF": 5, "SP": 2}
    assert rebuilt.pdcr_resolved_against_snapshot_id == 7
