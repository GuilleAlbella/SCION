"""Parse the DataDNA parser JSON feed into SCION's internal dataclasses.

This module is format-version tolerant: it reads the parser v1 shape (the
one Rahul's team ships today) and fills in Optional fields with None when
the parser hasn't emitted them yet. As future parser versions add fields,
this is the only file that needs updating.

Does NOT persist anything. Does NOT apply the noise filter. Its single
responsibility is: raw dict-like input → validated `ParsedLineagePayload`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping

from .parser_models import (
    ParsedAttribute,
    ParsedAttributeLineage,
    ParsedContainer,
    ParsedDataset,
    ParsedDatasetLineage,
    ParsedLineagePayload,
    ParsedPlatform,
    ParsedProcess,
    ParsedProcessGroup,
    ParsedStep,
)


class ParserPayloadError(ValueError):
    """Raised when the parser JSON is unusable (missing required keys, bad types)."""


def _require(payload: Mapping[str, Any], key: str) -> Any:
    """Tiny helper: fetch a required top-level key or fail with a clear message."""
    if key not in payload:
        raise ParserPayloadError(f"Missing required top-level key: '{key}'")
    return payload[key]


def _parse_timestamp(value: Any) -> datetime:
    """Parse parser timestamps (ISO 8601 with microseconds + tz)."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ParserPayloadError(f"Expected ISO timestamp string, got {type(value).__name__}")
    # Parser emits e.g. "2026-04-20T18:08:27.838179+00:00" — fromisoformat
    # handles both "+00:00" and microseconds natively in Python 3.11+.
    return datetime.fromisoformat(value)


def parse(payload: Mapping[str, Any]) -> ParsedLineagePayload:
    """Convert a raw parser-JSON dict into a `ParsedLineagePayload`.

    Args:
        payload: The decoded JSON (already `json.loads`-ed) from the parser.

    Returns:
        A fully populated `ParsedLineagePayload` with all arrays mapped to
        their dataclass equivalents. Fields not present in parser v1 are
        left as ``None`` / defaults.

    Raises:
        ParserPayloadError: when required keys are missing or malformed.
    """

    # ──── 1. Run-level metadata ────
    # `parseRunId` and `parseTimestamp` are the identity of this payload.
    # They appear at the top AND are repeated on every row; we trust the
    # top-level versions as the authoritative ones for the snapshot.
    parse_run_id = _require(payload, "parseRunId")
    parse_timestamp = _parse_timestamp(_require(payload, "parseTimestamp"))

    # ──── 2. Platform ────
    raw_platform = _require(payload, "platform")
    platform = ParsedPlatform(
        platform_natural_key=raw_platform.get("platformNaturalKey", "UNKNOWN"),
        technology=raw_platform.get("technology"),
    )

    # ──── 3. Containers → databases in SCION ────
    containers = [
        ParsedContainer(
            container_natural_key=c.get("containerNaturalKey", ""),
            platform_natural_key=c.get("platformNaturalKey", platform.platform_natural_key),
            technology=c.get("technology"),
        )
        for c in payload.get("containers", [])
    ]

    # ──── 4. Datasets (tables/views) ────
    # `datasetType` isn't in parser v1 — left None and will default to
    # "UNKNOWN" during persistence until the parser team adds it.
    datasets = [
        ParsedDataset(
            dataset_natural_key=d.get("datasetNaturalKey", ""),
            container_natural_key=d.get("containerNaturalKey", ""),
            platform_natural_key=d.get("platformNaturalKey", platform.platform_natural_key),
            technology=d.get("technology"),
            dataset_type=d.get("datasetType"),  # future-proof
        )
        for d in payload.get("datasets", [])
    ]

    # ──── 5. Attributes (columns + noise) ────
    # Parser v1 mixes real columns and SQL literals (e.g. `'D'`, `NULL`) here.
    # We KEEP them at parse time — classification happens in noise_filter.py.
    # dataType / nullable / ordinalPosition are future-proofed the same way.
    attributes = [
        ParsedAttribute(
            attribute_natural_key=a.get("attributeNaturalKey", ""),
            dataset_natural_key=a.get("datasetNaturalKey", ""),
            container_natural_key=a.get("containerNaturalKey", ""),
            platform_natural_key=a.get("platformNaturalKey", platform.platform_natural_key),
            technology=a.get("technology"),
            data_type=a.get("dataType"),
            nullable=a.get("nullable"),
            ordinal_position=a.get("ordinalPosition"),
            attribute_class=a.get("attributeClass"),  # future-proof
        )
        for a in payload.get("attributes", [])
    ]

    # ──── 6. Process groups + processes + steps ────
    process_groups = [
        ParsedProcessGroup(
            process_group_natural_key=pg.get("processGroupNaturalKey", ""),
            platform_natural_key=pg.get("platformNaturalKey", platform.platform_natural_key),
        )
        for pg in payload.get("processGroups", [])
    ]

    processes = [
        ParsedProcess(
            process_natural_key=p.get("processNaturalKey", ""),
            process_type=p.get("processType"),
            process_group_natural_key=p.get("processGroupNaturalKey"),
            platform_natural_key=p.get("platformNaturalKey", platform.platform_natural_key),
        )
        for p in payload.get("processes", [])
    ]

    steps = [
        ParsedStep(
            step_natural_key=s.get("stepNaturalKey", ""),
            process_natural_key=s.get("processNaturalKey", ""),
            step_level=s.get("stepLevel"),
            step_type=s.get("stepType"),
            parent_step_natural_key=s.get("parentStepNaturalKey"),
            process_group_natural_key=s.get("processGroupNaturalKey"),
            platform_natural_key=s.get("platformNaturalKey", platform.platform_natural_key),
        )
        for s in payload.get("steps", [])
    ]

    # ──── 7. Dataset-level lineage (Tier 3) — maps to graph_edge ────
    dataset_lineage = [
        ParsedDatasetLineage(
            source_dataset_natural_key=e.get("sourceDatasetNaturalKey", ""),
            target_dataset_natural_key=e.get("targetDatasetNaturalKey", ""),
            source_container_natural_key=e.get("sourceContainerNaturalKey"),
            source_platform_natural_key=e.get("sourcePlatformNaturalKey"),
            target_container_natural_key=e.get("targetContainerNaturalKey"),
            target_platform_natural_key=e.get("targetPlatformNaturalKey"),
            step_natural_key=e.get("stepNaturalKey"),
            impact_type=e.get("impactType"),
        )
        for e in payload.get("tier3DatasetLineage", [])
    ]

    # ──── 8. Attribute-level lineage (Tier 1 + Tier 2) ────
    # We collect BOTH tiers here and tag each with the source array name.
    # The consolidated `lineageFactAttribute` is superset — skip if present
    # to avoid duplicates, else fall back to tier1+tier2.
    attribute_lineage: list[ParsedAttributeLineage] = []
    has_fact = "lineageFactAttribute" in payload and payload["lineageFactAttribute"]

    if has_fact:
        for e in payload["lineageFactAttribute"]:
            attribute_lineage.append(_make_attr_lineage(e, tier="FACT"))
    else:
        for e in payload.get("tier1QueryBlockAttributeLineage", []):
            attribute_lineage.append(_make_attr_lineage(e, tier="TIER1"))
        for e in payload.get("tier2StatementAttributeLineage", []):
            attribute_lineage.append(_make_attr_lineage(e, tier="TIER2"))

    # ──── 9. Assemble and return ────
    result = ParsedLineagePayload(
        parse_run_id=parse_run_id,
        parse_timestamp=parse_timestamp,
        platform=platform,
        containers=containers,
        datasets=datasets,
        attributes=attributes,
        process_groups=process_groups,
        processes=processes,
        steps=steps,
        dataset_lineage=dataset_lineage,
        attribute_lineage=attribute_lineage,
    )
    # Record input counts — useful for the ingestion report UI.
    result.stats["input"] = {
        "containers": len(containers),
        "datasets": len(datasets),
        "attributes": len(attributes),
        "process_groups": len(process_groups),
        "processes": len(processes),
        "steps": len(steps),
        "dataset_lineage": len(dataset_lineage),
        "attribute_lineage": len(attribute_lineage),
    }
    return result


def _make_attr_lineage(e: Mapping[str, Any], tier: str) -> ParsedAttributeLineage:
    """Shared mapper for the three attribute-lineage arrays (same shape)."""
    return ParsedAttributeLineage(
        source_attribute_natural_key=e.get("sourceAttributeNaturalKey", ""),
        target_attribute_natural_key=e.get("targetAttributeNaturalKey", ""),
        tier=tier,
        source_dataset_natural_key=e.get("sourceDatasetNaturalKey"),
        target_dataset_natural_key=e.get("targetDatasetNaturalKey"),
        step_natural_key=e.get("stepNaturalKey"),
        expression=e.get("expression"),
        transformation_type=e.get("transformationType"),
    )
