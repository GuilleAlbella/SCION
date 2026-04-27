"""Dry-run analyzer: report what an ingestion would do, without persisting.

Purpose: let users (and Rahul's team) feed a payload into SCION, see the
full stats — what would be kept, dropped, classified as what, which warnings
would fire — and decide whether to run the real ingestion.

Zero DB writes. Can be called safely in production without side effects.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .parser_models import IngestionReport, ParsedLineagePayload


def analyze(payload: ParsedLineagePayload) -> IngestionReport:
    """Simulate ingestion and return the same `IngestionReport` shape.

    The caller can run this, show the report to the user, and invoke the
    real `ingestor.ingest()` only when the user confirms.

    Args:
        payload: Parsed + noise-filtered payload.

    Returns:
        `IngestionReport` with `dry_run=True`, `snapshot_id=None`, and
        computed "would-persist" counts mirroring the real ingestor.
    """
    report = IngestionReport(
        dry_run=True,
        snapshot_id=None,
        parse_run_id=payload.parse_run_id,
        parse_timestamp=payload.parse_timestamp,
        input_counts=payload.stats.get("input", {}),
        filtered_counts=payload.stats.get("noise_filter", {}),
    )

    # Fast path: simulate the joins by counting what WOULD be persistable.
    # We don't recreate the full ingest logic — just check referential
    # integrity (does each dataset have a container we kept? does each
    # attribute have a dataset?) so the numbers match reality.

    # ──── Build fast lookups from what survived the filter ────
    container_keys = {c.container_natural_key for c in payload.containers}
    dataset_keys_with_container = {
        d.dataset_natural_key
        for d in payload.datasets
        if d.container_natural_key in container_keys
    }
    attributes_with_dataset = [
        a for a in payload.attributes
        if a.dataset_natural_key in dataset_keys_with_container
    ]

    # ──── Dataset lineage: endpoints must both resolve ────
    valid_dataset_edges = 0
    orphaned_dataset_edges: List[str] = []
    for e in payload.dataset_lineage:
        if e.source_dataset_natural_key in dataset_keys_with_container \
           and e.target_dataset_natural_key in dataset_keys_with_container:
            valid_dataset_edges += 1
        else:
            orphaned_dataset_edges.append(
                f"{e.source_dataset_natural_key} → {e.target_dataset_natural_key}"
            )

    # ──── Processes / steps referential integrity ────
    process_keys = {p.process_natural_key for p in payload.processes}
    orphan_steps = [s.step_natural_key for s in payload.steps
                    if s.process_natural_key not in process_keys]

    persisted_would_be: Dict[str, int] = {
        "databases": len(container_keys),
        "tables": len(dataset_keys_with_container),
        "columns": len(attributes_with_dataset),
        "graph_nodes": len(dataset_keys_with_container),
        "graph_edges": valid_dataset_edges,
        "processes": len(payload.processes),
        "steps": len(payload.steps) - len(orphan_steps),
        "attribute_lineage": len(payload.attribute_lineage),
    }
    report.persisted_counts = persisted_would_be

    # ──── Warnings ────
    if orphaned_dataset_edges:
        report.warnings.append(
            f"{len(orphaned_dataset_edges)} dataset lineage edge(s) would be "
            f"dropped because an endpoint was filtered out. First 3: "
            f"{', '.join(orphaned_dataset_edges[:3])}"
        )

    if orphan_steps:
        report.warnings.append(
            f"{len(orphan_steps)} step(s) reference unknown processes and "
            f"would be skipped. First 3: {', '.join(orphan_steps[:3])}"
        )

    # Surface the stub-field issue — it's the most important thing for the
    # demo audience to see.
    stub_datasets = sum(1 for d in payload.datasets if not d.dataset_type)
    if stub_datasets > 0:
        report.warnings.append(
            f"{stub_datasets} dataset(s) have no `datasetType` from the parser "
            f"— they will be stored as 'UNKNOWN' until parser v2. "
            f"Schema-change detection will not work on these until then."
        )

    stub_attrs = sum(1 for a in payload.attributes
                     if a.data_type is None and a.dataset_natural_key in dataset_keys_with_container)
    if stub_attrs > 0:
        report.warnings.append(
            f"{stub_attrs} column(s) have no `dataType` from the parser — "
            f"they will be stored as 'UNKNOWN'. Diff engine cannot detect "
            f"type changes on these until parser v2."
        )

    return report
