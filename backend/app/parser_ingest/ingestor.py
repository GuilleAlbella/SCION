"""Persist a `ParsedLineagePayload` into SCION's database tables.

Produces:

- One ``snapshot`` row   (from parse_run_id / parse_timestamp).
- One ``schema_snapshot`` per real container (database).
- One ``table_snapshot`` per real dataset (table/view).
- One ``column_snapshot`` per real attribute (column).
- One ``graph_node`` per container+dataset (so the graph page still works).
- One ``graph_edge`` per ``ParsedDatasetLineage`` (Tier 3).
- One ``process`` per ``ParsedProcess``.
- One ``step`` per ``ParsedStep``.
- One ``attribute_lineage`` per ``ParsedAttributeLineage`` (Tier 1/2).

Stubs used until parser v2 lands:

- ``table_snapshot.object_type`` → ``"UNKNOWN"`` if parser didn't send
  ``datasetType``. Will switch to the real value automatically when Rahul
  adds it.
- ``column_snapshot.data_type`` → ``"UNKNOWN"``. Same story.
- ``column_snapshot.nullable`` → ``True`` (permissive default).
- ``column_snapshot.ordinal_position`` → deterministic index within table.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .parser_models import IngestionReport, ParsedLineagePayload

# NOTE: All SQLAlchemy model imports are done LAZILY inside `ingest()`.
# The project uses `app.db.base` as the eager-import aggregator — importing
# any model at module load here creates a circular import chain through
# base.py → diff_models → column_snapshot → … while base.py is still
# initializing. Late imports avoid the cycle and match the pattern used by
# the rest of `app/api/v1/` endpoints.


def ingest(
    payload: ParsedLineagePayload,
    *,
    source_system: Optional[str] = None,
    description: Optional[str] = None,
) -> IngestionReport:
    """Persist `payload` into SCION and return an ingestion report.

    All inserts happen within a single transaction — if any row fails,
    the whole snapshot is rolled back. Caller gets the surrogate snapshot_id.

    Args:
        payload: Validated, noise-filtered payload.
        source_system: Override for ``snapshot.source_system``. If omitted,
            derived from ``payload.platform.platform_natural_key``.
        description: Optional free-text description for the snapshot.

    Returns:
        `IngestionReport` with snapshot_id, input counts, and persisted counts.
    """
    # Late imports (see module header note). We touch `app.db.base` first so
    # its eager aggregator-imports (diff_models, graph_models, etc.) run in a
    # predictable order before we pull in individual ORM classes. This works
    # around a cold-start circular-import that otherwise fires when the very
    # first model resolution in a process is `ColumnSnapshot`.
    import app.db.base  # noqa: F401 — side-effect eager load

    from sqlalchemy.orm import Session
    from app.db.engine import engine
    from app.db.models.column_snapshot import ColumnSnapshot
    from app.db.models.schema_snapshot import SchemaSnapshot
    from app.db.models.snapshot import Snapshot
    from app.db.models.table_snapshot import TableSnapshot
    from app.db.models.process import Process
    from app.db.models.step import Step
    from app.db.models.attribute_lineage import AttributeLineage
    from app.graph.graph_models import GraphEdge, GraphNode

    report = IngestionReport(
        dry_run=False,
        snapshot_id=None,
        parse_run_id=payload.parse_run_id,
        parse_timestamp=payload.parse_timestamp,
        input_counts=payload.stats.get("input", {}),
        filtered_counts=payload.stats.get("noise_filter", {}),
    )

    persisted: Dict[str, int] = {
        "databases": 0, "tables": 0, "columns": 0,
        "graph_nodes": 0, "graph_edges": 0,
        "processes": 0, "steps": 0, "attribute_lineage": 0,
    }

    with Session(bind=engine) as session:
        with session.begin():
            # ──── 1. Create the Snapshot row ────
            snap = Snapshot(
                snapshot_time=payload.parse_timestamp,
                source_system=source_system
                    or f"parser:{payload.platform.platform_natural_key}",
                description=description
                    or f"Parser run {payload.parse_run_id}",
                is_baseline=False,
            )
            session.add(snap)
            session.flush()  # force PK assignment so FKs below can reference it
            report.snapshot_id = snap.snapshot_id

            # ──── 2. Containers → schema_snapshot ────
            # Maps container natural key → inserted schema_id for dataset lookups.
            schema_id_by_container: Dict[str, int] = {}
            for c in payload.containers:
                schema_row = SchemaSnapshot(
                    snapshot_id=snap.snapshot_id,
                    schema_name=c.container_natural_key,
                )
                session.add(schema_row)
                session.flush()
                schema_id_by_container[c.container_natural_key] = schema_row.schema_id
                persisted["databases"] += 1

            # ──── 3. Datasets → table_snapshot + graph_node ────
            # The parser's dataset name is "container.table"; we strip the
            # container prefix to match SCION's existing table_name format.
            # Datasets orphaned (no container match) are skipped — that can
            # happen when noise_filter dropped the container but left a
            # dataset referencing it.
            table_id_by_dataset: Dict[str, int] = {}
            node_id_by_dataset: Dict[str, str] = {}
            for d in payload.datasets:
                schema_id = schema_id_by_container.get(d.container_natural_key)
                if schema_id is None:
                    report.warnings.append(
                        f"Dataset {d.dataset_natural_key!r} has unknown container "
                        f"{d.container_natural_key!r} — skipped."
                    )
                    continue

                table_name = _strip_prefix(d.dataset_natural_key, d.container_natural_key + ".")
                object_type = _map_dataset_type(d.dataset_type)

                t = TableSnapshot(
                    schema_id=schema_id,
                    table_name=table_name,
                    object_type=object_type,
                )
                session.add(t)
                session.flush()
                table_id_by_dataset[d.dataset_natural_key] = t.table_id
                persisted["tables"] += 1

                # Also create the graph node so the Graph page works.
                # node_uid uses the parser's dataset_natural_key for stable
                # cross-referencing with edges (which also use natural keys).
                node = GraphNode(
                    object_type=object_type,
                    object_name=d.dataset_natural_key,
                    snapshot_id=snap.snapshot_id,
                    schema_name=d.container_natural_key,
                    node_uid=d.dataset_natural_key,
                )
                session.add(node)
                session.flush()
                node_id_by_dataset[d.dataset_natural_key] = node.node_id
                persisted["graph_nodes"] += 1

            # ──── 4. Attributes → column_snapshot ────
            # Group by dataset so we can assign deterministic ordinal positions
            # when the parser hasn't emitted them. Order within group uses
            # first-seen (list position) as a stable proxy.
            ordinal_counter: Dict[str, int] = {}
            for a in payload.attributes:
                table_id = table_id_by_dataset.get(a.dataset_natural_key)
                if table_id is None:
                    # Attribute's table was filtered out or unknown.
                    report.warnings.append(
                        f"Attribute {a.attribute_natural_key!r} has unknown "
                        f"dataset {a.dataset_natural_key!r} — skipped."
                    )
                    continue

                # Extract bare column name from "dataset|column" natural key.
                # Parser separator is `|`; fall back to the whole key if no sep.
                column_name = a.attribute_natural_key.split("|", 1)[-1] \
                    if "|" in a.attribute_natural_key else a.attribute_natural_key

                # Ordinal: use the parser's if present, else monotonic per table.
                if a.ordinal_position is not None:
                    ordinal = a.ordinal_position
                else:
                    ordinal_counter[a.dataset_natural_key] = \
                        ordinal_counter.get(a.dataset_natural_key, 0) + 1
                    ordinal = ordinal_counter[a.dataset_natural_key]

                col = ColumnSnapshot(
                    table_id=table_id,
                    column_name=column_name,
                    data_type=a.data_type or "UNKNOWN",
                    nullable=a.nullable if a.nullable is not None else True,
                    ordinal_position=ordinal,
                )
                session.add(col)
                persisted["columns"] += 1

            # ──── 5. Processes and steps ────
            # Two passes: processes first so steps can reference the FK.
            process_id_by_natural: Dict[str, int] = {}
            for p in payload.processes:
                proc = Process(
                    snapshot_id=snap.snapshot_id,
                    process_natural_key=p.process_natural_key,
                    process_type=p.process_type,
                    process_group_natural_key=p.process_group_natural_key,
                    platform_natural_key=p.platform_natural_key,
                    parse_run_id=payload.parse_run_id,
                    parse_timestamp=payload.parse_timestamp,
                )
                session.add(proc)
                session.flush()
                process_id_by_natural[p.process_natural_key] = proc.process_id
                persisted["processes"] += 1

            for s in payload.steps:
                process_id = process_id_by_natural.get(s.process_natural_key)
                if process_id is None:
                    report.warnings.append(
                        f"Step {s.step_natural_key!r} references unknown "
                        f"process {s.process_natural_key!r} — skipped."
                    )
                    continue

                step_row = Step(
                    snapshot_id=snap.snapshot_id,
                    step_natural_key=s.step_natural_key,
                    process_id=process_id,
                    parent_step_natural_key=s.parent_step_natural_key,
                    step_level=s.step_level,
                    step_type=s.step_type,
                    platform_natural_key=s.platform_natural_key,
                    parse_run_id=payload.parse_run_id,
                    parse_timestamp=payload.parse_timestamp,
                )
                session.add(step_row)
                persisted["steps"] += 1

            # ──── 6. Dataset lineage → graph_edge ────
            # `node_id_by_dataset` was built in step 3; edges to unknown
            # datasets are dropped (noise_filter should have done it, but
            # we double-check here so nothing dangling slips through).
            for e in payload.dataset_lineage:
                src = node_id_by_dataset.get(e.source_dataset_natural_key)
                tgt = node_id_by_dataset.get(e.target_dataset_natural_key)
                if src is None or tgt is None:
                    report.warnings.append(
                        f"Dataset lineage edge "
                        f"{e.source_dataset_natural_key!r} → "
                        f"{e.target_dataset_natural_key!r} has missing endpoint — skipped."
                    )
                    continue

                edge = GraphEdge(
                    snapshot_id=snap.snapshot_id,
                    source_node_id=src,
                    target_node_id=tgt,
                    relationship_type="FEEDS",
                    from_node_uid=e.source_dataset_natural_key,
                    to_node_uid=e.target_dataset_natural_key,
                    edge_type="FEEDS",
                    edge_metadata={
                        "impact_type": e.impact_type,
                        "step_natural_key": e.step_natural_key,
                    },
                )
                session.add(edge)
                persisted["graph_edges"] += 1

            # ──── 7. Attribute-level lineage ────
            for e in payload.attribute_lineage:
                row = AttributeLineage(
                    snapshot_id=snap.snapshot_id,
                    source_attribute_natural_key=e.source_attribute_natural_key,
                    source_dataset_natural_key=e.source_dataset_natural_key,
                    target_attribute_natural_key=e.target_attribute_natural_key,
                    target_dataset_natural_key=e.target_dataset_natural_key,
                    step_natural_key=e.step_natural_key,
                    tier=e.tier,
                    expression=e.expression,
                    transformation_type=e.transformation_type,
                    parse_run_id=payload.parse_run_id,
                    parse_timestamp=payload.parse_timestamp,
                )
                session.add(row)
                persisted["attribute_lineage"] += 1

            # Attach total object count to the snapshot for the metrics page.
            snap.object_count = (
                persisted["databases"] + persisted["tables"] + persisted["columns"]
            )

    report.persisted_counts = persisted
    return report


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def _strip_prefix(s: str, prefix: str) -> str:
    """Remove `prefix` from `s` if present; otherwise return `s` unchanged.

    Used to convert the parser's "container.table" dataset natural key into
    SCION's bare table name (because the container is already modelled
    separately as schema_snapshot).
    """
    return s[len(prefix):] if s.startswith(prefix) else s


# Parser `datasetType` → SCION `object_type`. Kept small and explicit;
# unknown values fall through as-is (uppercased). Will be extended as we
# see more Teradata TableKind variants in real data.
_DATASET_TYPE_MAP = {
    "TABLE": "TABLE",
    "VIEW": "VIEW",
    "STORED_PROCEDURE": "STORED_PROCEDURE",
    "MACRO": "MACRO",
    "FUNCTION": "FUNCTION",
    "UDF": "UDF",
    "TRIGGER": "TRIGGER",
    "INDEX": "INDEX",
    "SEQUENCE": "SEQUENCE",
}


def _map_dataset_type(dataset_type: Optional[str]) -> str:
    """Normalize parser `datasetType` to SCION's `object_type` enumeration.

    Until the parser emits a real value (v2 request), this just returns
    ``"UNKNOWN"`` — SCION's UI already renders UNKNOWN nodes with a neutral
    style so this is a safe placeholder.
    """
    if not dataset_type:
        return "UNKNOWN"
    return _DATASET_TYPE_MAP.get(dataset_type.upper().strip(), dataset_type.upper())
