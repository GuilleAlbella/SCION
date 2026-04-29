#!/usr/bin/env python3
"""End-to-end ingest benchmark for SCION.

Runs a full dict-import against a temp SQLite DB and prints the
metrics that `docs/internal_roadmap.md` §1.1 lists as decision-driving
for the SQLite-vs-Postgres / VM-sizing call:

    - object count (tables + views + procs)
    - edge count
    - .db size on disk
    - wall time for: parse, validate, persist, post-ingest pipeline
    - peak RSS RAM during the run

Designed for any sample, not just the first one. Pass a folder via
`--sample-dir`; the script picks up whichever of the 6 dict views
are present and ignores the rest. With Rahul's eventual full extract,
this is the script we'll point at the data to decide whether SQLite
holds up or we need to migrate to Postgres before pilot.

Why a dedicated benchmark script (vs. just timing pytest):

  - pytest tears down per-test, so it can't measure "what happens
    when we ingest a real-world-sized batch all at once".
  - The post-ingest pipeline (graph build, criticality, etc.) is the
    actual hot path that scales with the data; pytest fixtures hide
    its cost behind smaller per-test snapshots.
  - We want the report formatted for an email / PR comment, not a
    pytest log.

Run:
    python tools/benchmark_ingest.py --sample-dir "Parser/Data extract 2/Sample 1"

On Windows, run from a developer shell with the venv activated
(otherwise ``app.*`` imports won't resolve).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# `resource` is POSIX-only; on Windows we'd need psutil. Both are
# optional — if neither is available we report NaN for peak RSS and
# move on. The timings + DB size are the load-bearing metrics anyway.
_HAS_RESOURCE = False
_HAS_PSUTIL = False
try:
    import resource  # type: ignore
    _HAS_RESOURCE = True
except ImportError:
    try:
        import psutil  # type: ignore
        _HAS_PSUTIL = True
    except ImportError:
        pass


# ──── Make `app` importable when run from project root ────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_PATH = PROJECT_ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))


@dataclass
class BenchmarkResult:
    """Single run's measurements. Plain values so we can dump as
    JSON, paste into a GitHub comment, or feed into a spreadsheet."""
    sample_name: str
    parse_seconds: float
    validate_seconds: float
    persist_seconds: float
    postingest_seconds: float
    total_seconds: float
    db_size_bytes: int
    peak_rss_mb: float
    schemas: int
    tables: int
    columns: int
    indices: int
    partitioning: int
    ddl_text: int
    graph_nodes: int
    graph_edges: int


def _peak_rss_mb() -> float:
    """Best-effort peak resident set size in megabytes.

    POSIX: ru_maxrss from `resource` (KB on Linux, bytes on macOS).
    Windows: psutil.Process().memory_info().peak_wset (bytes).
    Neither available: NaN — better than crashing, the report still
    prints the timings.
    """
    if _HAS_RESOURCE:
        # Linux reports KB; macOS reports bytes. Detect by size.
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # type: ignore
        # Heuristic: if rss > 10**8 we're on macOS (bytes); else KB.
        if rss > 100_000_000:
            return rss / (1024 * 1024)
        return rss / 1024
    if _HAS_PSUTIL:
        try:
            return psutil.Process().memory_info().peak_wset / (1024 * 1024)  # type: ignore
        except Exception:
            return float("nan")
    return float("nan")


def _file_size(path: Path) -> int:
    """File size in bytes, 0 if missing (so the print line never blows up)."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def run(sample_dir: Path) -> BenchmarkResult:
    """Execute the full ingest end-to-end against a fresh temp DB."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    # Late imports so PROJECT_ROOT path manipulation above kicks in.
    import app.db.base  # noqa: F401 — registers all models
    from app.db.base import Base
    from app.db.models.snapshot import Snapshot
    from app.metadata import (
        dict_flat_file_reader as r,
        dict_batch_validator,
        dict_persister,
    )

    # Brand new engine on a temp DB so we benchmark cold-cache writes.
    db_path = Path(tempfile.gettempdir()) / f"scion_bench_{os.getpid()}.db"
    if db_path.exists():
        db_path.unlink()
    test_engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(bind=test_engine)

    # ──── 1. Parse ────
    # Map filename prefix → reader function so any combination of the
    # 6 files is handled. Missing files are silently skipped (ingest
    # treats them as empty lists).
    READERS = {
        "databasesv_": r.read_databases,
        "tablesv_": r.read_tables,
        "columnsv_": r.read_columns,
        "indicesv_": r.read_indices,
        "partitioningconstraintsv_": r.read_partitioning,
        "tabletextv_": r.read_tabletext,
    }
    by_category: dict[str, list] = {
        "databases": [], "tables": [], "columns": [],
        "indices": [], "partitioning": [], "tabletext": [],
    }
    name_to_cat = {
        "databasesv_": "databases",
        "tablesv_": "tables",
        "columnsv_": "columns",
        "indicesv_": "indices",
        "partitioningconstraintsv_": "partitioning",
        "tabletextv_": "tabletext",
    }

    t0 = time.perf_counter()
    files_for_validator: list[tuple[str, list]] = []
    for f in sorted(sample_dir.glob("*.dat")):
        for prefix, reader in READERS.items():
            if f.name.lower().startswith(prefix):
                records = reader(f)
                cat = name_to_cat[prefix]
                by_category[cat].extend(records)
                files_for_validator.append((f.name, records))
                break
    t_parse = time.perf_counter() - t0

    # ──── 2. Validate ────
    t0 = time.perf_counter()
    identity = dict_batch_validator.validate_batch(files_for_validator)
    t_validate = time.perf_counter() - t0

    # ──── 3. Persist ────
    # We use the test_engine session directly (not the global one)
    # so the post-ingest helpers (which open their own sessions
    # against the global engine) don't pollute the production DB.
    # That means we have to re-bind the global engine just for this
    # process — temporarily swap DATABASE_URL so the helpers find
    # the temp DB.
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    # Force a re-import of engine so it picks up the env var.
    import importlib
    import app.db.engine
    importlib.reload(app.db.engine)

    t0 = time.perf_counter()
    with Session(bind=test_engine) as sess:
        result = dict_persister.persist_batch(
            session=sess,
            identity=identity,
            databases=by_category["databases"],
            tables=by_category["tables"],
            columns=by_category["columns"],
            indices=by_category["indices"],
            partitioning=by_category["partitioning"],
            tabletext=by_category["tabletext"],
        )
        sess.commit()
    t_persist = time.perf_counter() - t0

    # ──── 4. Post-ingest pipeline ────
    t0 = time.perf_counter()
    dict_persister.run_post_ingest_pipeline(result.snapshot_id)
    t_postingest = time.perf_counter() - t0

    # ──── Final inspection ────
    # Snapshot the graph counts after the pipeline finishes so we
    # can report the analytical-table fill, not just persist counts.
    from app.graph.graph_models import GraphNode, GraphEdge
    with Session(bind=test_engine) as sess:
        nodes_n = sess.query(GraphNode).filter(
            GraphNode.snapshot_id == result.snapshot_id
        ).count()
        edges_n = sess.query(GraphEdge).join(
            GraphNode, GraphEdge.source_node_id == GraphNode.node_id
        ).filter(GraphNode.snapshot_id == result.snapshot_id).count()

    return BenchmarkResult(
        sample_name=sample_dir.name,
        parse_seconds=t_parse,
        validate_seconds=t_validate,
        persist_seconds=t_persist,
        postingest_seconds=t_postingest,
        total_seconds=t_parse + t_validate + t_persist + t_postingest,
        db_size_bytes=_file_size(db_path),
        peak_rss_mb=_peak_rss_mb(),
        schemas=result.schemas_created,
        tables=result.tables_created,
        columns=result.columns_created,
        indices=result.indices_created,
        partitioning=result.partitioning_created,
        ddl_text=result.ddl_text_created,
        graph_nodes=nodes_n,
        graph_edges=edges_n,
    )


def print_report(b: BenchmarkResult) -> None:
    """Print a human-friendly report. Lines kept short enough for a
    Slack/Teams paste; the format is deliberately stable so a
    diff between two runs is easy to read."""
    print()
    print("====================================================================")
    print(f"  SCION ingest benchmark — {b.sample_name}")
    print("====================================================================")
    print()
    print("  Wall time")
    print(f"    parse              {b.parse_seconds*1000:8.1f} ms")
    print(f"    validate           {b.validate_seconds*1000:8.1f} ms")
    print(f"    persist            {b.persist_seconds*1000:8.1f} ms")
    print(f"    post-ingest        {b.postingest_seconds*1000:8.1f} ms")
    print(f"    total              {b.total_seconds*1000:8.1f} ms")
    print()
    print("  Memory & disk")
    print(f"    peak RSS           {b.peak_rss_mb:8.1f} MB")
    print(f"    .db size           {b.db_size_bytes/1024:8.1f} KB")
    print()
    print("  Persisted counts")
    print(f"    schemas            {b.schemas}")
    print(f"    tables / views     {b.tables}")
    print(f"    columns            {b.columns}")
    print(f"    indices            {b.indices}")
    print(f"    partitioning       {b.partitioning}")
    print(f"    DDL text records   {b.ddl_text}")
    print()
    print("  Graph (post-ingest)")
    print(f"    nodes              {b.graph_nodes}")
    print(f"    edges              {b.graph_edges}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--sample-dir",
        type=Path,
        required=True,
        help="Folder containing the 6 .dat files (any subset is fine).",
    )
    args = ap.parse_args()

    if not args.sample_dir.is_dir():
        print(f"error: --sample-dir is not a directory: {args.sample_dir}", file=sys.stderr)
        return 2

    result = run(args.sample_dir)
    print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
