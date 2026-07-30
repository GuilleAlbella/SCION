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

- ``table_snapshot.object_type`` â†’ ``"UNKNOWN"`` if parser didn't send
  ``datasetType``. Will switch to the real value automatically when Rahul
  adds it.
- ``column_snapshot.data_type`` â†’ ``"UNKNOWN"``. Same story.
- ``column_snapshot.nullable`` â†’ ``True`` (permissive default).
- ``column_snapshot.ordinal_position`` â†’ deterministic index within table.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .parser_models import IngestionReport, ParsedLineagePayload

# NOTE: All SQLAlchemy model imports are done LAZILY inside `ingest()`.
# The project uses `app.db.base` as the eager-import aggregator â€” importing
# any model at module load here creates a circular import chain through
# base.py â†’ diff_models â†’ column_snapshot â†’ â€¦ while base.py is still
# initializing. Late imports avoid the cycle and match the pattern used by
# the rest of `app/api/v1/` endpoints.


def ingest(
    payload: ParsedLineagePayload,
    *,
    source_system: Optional[str] = None,
    description: Optional[str] = None,
    attach_to_snapshot_id: Optional[int] = None,
) -> IngestionReport:
    """Persist `payload` into SCION and return an ingestion report.

    All inserts happen within a single transaction â€” if any row fails,
    the whole snapshot is rolled back. Caller gets the surrogate snapshot_id.

    Args:
        payload: Validated, noise-filtered payload.
        source_system: Override for ``snapshot.source_system``. If omitted,
            derived from ``payload.platform.platform_natural_key``.
        description: Optional free-text description for the snapshot.
        attach_to_snapshot_id: If given, lineage data is attached to this
            existing snapshot instead of creating a new one. Useful for
            unified imports where dict data was already ingested first.

    Returns:
        `IngestionReport` with snapshot_id, input counts, and persisted counts.
    """
    # Late imports (see module header note). We touch `app.db.base` first so
    # its eager aggregator-imports (diff_models, graph_models, etc.) run in a
    # predictable order before we pull in individual ORM classes. This works
    # around a cold-start circular-import that otherwise fires when the very
    # first model resolution in a process is `ColumnSnapshot`.
    import app.db.base  # noqa: F401 â€” side-effect eager load

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

    with Session(engine) as session:
        with session.begin():
            # â”€â”€â”€â”€ 1. Create or reuse Snapshot row â”€â”€â”€â”€
            if attach_to_snapshot_id is not None:
                from sqlalchemy import select as _select
                snap = session.execute(
                    _select(Snapshot).where(Snapshot.snapshot_id == attach_to_snapshot_id)
                ).scalar_one_or_none()
                if snap is None:
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=404,
                        detail=f"Snapshot {attach_to_snapshot_id} not found.",
                    )
            else:
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

            # â”€â”€â”€â”€ 2. Containers â†’ schema_snapshot â”€â”€â”€â”€
            # Maps container natural key â†’ inserted schema_id for dataset lookups.
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

            # â”€â”€â”€â”€ 3. Datasets â†’ table_snapshot + graph_node â”€â”€â”€â”€
            # The parser's dataset name is "container.table"; we strip the
            # container prefix to match SCION's existing table_name format.
            # Datasets orphaned (no container match) are skipped â€” that can
            # happen when noise_filter dropped the container but left a
            # dataset referencing it.
            table_id_by_dataset: Dict[str, int] = {}
            node_id_by_dataset: Dict[str, str] = {}
            for d in payload.datasets:
                schema_id = schema_id_by_container.get(d.container_natural_key)
                if schema_id is None:
                    report.warnings.append(
                        f"Dataset {d.dataset_natural_key!r} has unknown container "
                        f"{d.container_natural_key!r} â€” skipped."
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
                    object_name=d.dataset_natural_key.upper(),
                    snapshot_id=snap.snapshot_id,
                    schema_name=d.container_natural_key.upper() if d.container_natural_key else d.container_natural_key,
                    node_uid=d.dataset_natural_key,
                )
                session.add(node)
                session.flush()
                node_id_by_dataset[d.dataset_natural_key] = node.node_id
                persisted["graph_nodes"] += 1

            # â”€â”€â”€â”€ 4. Attributes â†’ column_snapshot â”€â”€â”€â”€
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
                        f"dataset {a.dataset_natural_key!r} â€” skipped."
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

            # â”€â”€â”€â”€ 5. Processes and steps â”€â”€â”€â”€
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
                        f"process {s.process_natural_key!r} â€” skipped."
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

            # â”€â”€â”€â”€ 6. Dataset lineage â†’ graph_edge â”€â”€â”€â”€
            # `node_id_by_dataset` was built in step 3; edges to unknown
            # datasets are dropped (noise_filter should have done it, but
            # we double-check here so nothing dangling slips through).
            # We also deduplicate: the parser emits one edge per SQL step
            # that uses the relationship, so the same (source, target) pair
            # can appear hundreds of times. We keep only the first occurrence
            # per (source_node_id, target_node_id) pair to avoid flooding the
            # graph with redundant edges that degrade BFS performance and
            # produce visual noise in the lineage view.
            seen_edge_pairs: set[Tuple[int, int]] = set()
            for e in payload.dataset_lineage:
                src = node_id_by_dataset.get(e.source_dataset_natural_key)
                tgt = node_id_by_dataset.get(e.target_dataset_natural_key)
                if src is None or tgt is None:
                    report.warnings.append(
                        f"Dataset lineage edge "
                        f"{e.source_dataset_natural_key!r} â†’ "
                        f"{e.target_dataset_natural_key!r} has missing endpoint â€” skipped."
                    )
                    continue

                pair = (src, tgt)
                if pair in seen_edge_pairs:
                    continue
                seen_edge_pairs.add(pair)

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

            # â”€â”€â”€â”€ 6.5. Resolve UNKNOWN-schema references via attribute lineage â”€â”€â”€â”€
            # The parser emits UNKNOWN.<Name> when it can't infer the schema
            # from the SQL context. Noise-filter drops those datasets as
            # unresolvable containers, so their edges are missing from step 6.
            # Here we scan attribute_lineage for edges that touch an UNKNOWN
            # endpoint. If the bare object name uniquely matches exactly one
            # real node in this snapshot, we emit the graph_edge so lineage
            # remains visible. Ambiguous names (same table in multiple schemas)
            # are skipped â€” better to show nothing than to show the wrong link.
            node_ids_by_bare_name: Dict[str, List[int]] = {}
            for key, nid in node_id_by_dataset.items():
                if "." in key:
                    node_ids_by_bare_name.setdefault(key.split(".", 1)[1], []).append(nid)

            for e in payload.attribute_lineage:
                src_key = e.source_dataset_natural_key or ""
                tgt_key = e.target_dataset_natural_key or ""
                src_unknown = src_key.upper().startswith("UNKNOWN.")
                tgt_unknown = tgt_key.upper().startswith("UNKNOWN.")
                if not src_unknown and not tgt_unknown:
                    continue

                if src_unknown:
                    cands = node_ids_by_bare_name.get(src_key[8:], [])
                    src_id = cands[0] if len(cands) == 1 else None
                else:
                    src_id = node_id_by_dataset.get(src_key)

                if tgt_unknown:
                    cands = node_ids_by_bare_name.get(tgt_key[8:], [])
                    tgt_id = cands[0] if len(cands) == 1 else None
                else:
                    tgt_id = node_id_by_dataset.get(tgt_key)

                if src_id is None or tgt_id is None or src_id == tgt_id:
                    continue
                pair = (src_id, tgt_id)
                if pair in seen_edge_pairs:
                    continue
                seen_edge_pairs.add(pair)
                edge = GraphEdge(
                    snapshot_id=snap.snapshot_id,
                    source_node_id=src_id,
                    target_node_id=tgt_id,
                    relationship_type="FEEDS",
                    from_node_uid=src_key,
                    to_node_uid=tgt_key,
                    edge_type="FEEDS",
                    edge_metadata={
                        "impact_type": "Direct",
                        "step_natural_key": e.step_natural_key,
                        "resolved_from_unknown": True,
                    },
                )
                session.add(edge)
                persisted["graph_edges"] += 1

            # â”€â”€â”€â”€ 7. Attribute-level lineage â”€â”€â”€â”€
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

            # Attach total object count to parser-created snapshots only. When
            # lineage is attached to an existing dict snapshot, preserve the
            # dictionary object's headline count instead of replacing it with
            # the smaller parser payload count.
            if attach_to_snapshot_id is None:
                snap.object_count = (
                    persisted["databases"] + persisted["tables"] + persisted["columns"]
                )

    report.persisted_counts = persisted
    return report


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _strip_prefix(s: str, prefix: str) -> str:
    """Remove `prefix` from `s` if present; otherwise return `s` unchanged.

    Used to convert the parser's "container.table" dataset natural key into
    SCION's bare table name (because the container is already modelled
    separately as schema_snapshot).
    """
    return s[len(prefix):] if s.startswith(prefix) else s


# Parser `datasetType` â†’ SCION `object_type`. Kept small and explicit;
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
    ``"UNKNOWN"`` â€” SCION's UI already renders UNKNOWN nodes with a neutral
    style so this is a safe placeholder.
    """
    if not dataset_type:
        return "UNKNOWN"
    return _DATASET_TYPE_MAP.get(dataset_type.upper().strip(), dataset_type.upper())
