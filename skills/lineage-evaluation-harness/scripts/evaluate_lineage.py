#!/usr/bin/env python3
"""Evaluate DataDNA lineage JSON without parsing SQL.

The script performs deterministic checks over parser output:
  * contract/invariant validation for actual JSON
  * semantic diff against optional approved expected JSON
  * Markdown + JSON report output
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


VOLATILE_KEYS = {
    "parseRunId",
    "parseTimestamp",
    "metadata",
}

ATTRIBUTE_SENTINELS = {"<*>", "NOT APPLICABLE"}

COLLECTIONS = [
    "containers",
    "datasets",
    "attributes",
    "processGroups",
    "processes",
    "steps",
    "tier1QueryBlockAttributeLineage",
    "tier2StatementAttributeLineage",
    "tier3DatasetLineage",
    "lineageFactAttribute",
]

SIGNATURE_FIELDS: dict[str, list[str]] = {
    "containers": ["containerNaturalKey", "platformNaturalKey", "technology"],
    "datasets": ["datasetNaturalKey", "containerNaturalKey", "platformNaturalKey"],
    "attributes": ["attributeNaturalKey", "datasetNaturalKey", "containerNaturalKey", "platformNaturalKey"],
    "processGroups": ["processGroupNaturalKey", "platformNaturalKey"],
    "processes": ["processNaturalKey", "processGroupNaturalKey", "processType", "platformNaturalKey"],
    "steps": ["stepNaturalKey", "processNaturalKey", "stepLevel", "stepType", "parentStepNaturalKey"],
    "tier1QueryBlockAttributeLineage": [
        "sourceAttributeNaturalKey",
        "sourceDatasetNaturalKey",
        "targetAttributeNaturalKey",
        "targetDatasetNaturalKey",
        "stepNaturalKey",
        "processNaturalKey",
        "expression",
    ],
    "tier2StatementAttributeLineage": [
        "sourceAttributeNaturalKey",
        "sourceDatasetNaturalKey",
        "targetAttributeNaturalKey",
        "targetDatasetNaturalKey",
        "stepNaturalKey",
        "processNaturalKey",
    ],
    "tier3DatasetLineage": [
        "sourceDatasetNaturalKey",
        "targetDatasetNaturalKey",
        "stepNaturalKey",
    ],
    "lineageFactAttribute": [
        "sourceAttributeNaturalKey",
        "sourceDatasetNaturalKey",
        "targetAttributeNaturalKey",
        "targetDatasetNaturalKey",
        "stepNaturalKey",
        "processNaturalKey",
        "stepType",
    ],
}

REQUIRED_LINEAGE_FIELDS: dict[str, list[str]] = {
    "tier1QueryBlockAttributeLineage": [
        "sourceAttributeNaturalKey",
        "sourceDatasetNaturalKey",
        "targetAttributeNaturalKey",
        "targetDatasetNaturalKey",
        "stepNaturalKey",
    ],
    "tier2StatementAttributeLineage": [
        "sourceAttributeNaturalKey",
        "sourceDatasetNaturalKey",
        "targetAttributeNaturalKey",
        "targetDatasetNaturalKey",
        "stepNaturalKey",
    ],
    "tier3DatasetLineage": [
        "sourceDatasetNaturalKey",
        "targetDatasetNaturalKey",
        "stepNaturalKey",
    ],
    "lineageFactAttribute": [
        "sourceAttributeNaturalKey",
        "sourceDatasetNaturalKey",
        "targetAttributeNaturalKey",
        "targetDatasetNaturalKey",
        "stepNaturalKey",
    ],
}


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    evidence: dict[str, Any]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object at top level")
    return data


def stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: stable_value(v) for k, v in sorted(value.items()) if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [stable_value(v) for v in value]
    return value


def signature(collection: str, row: dict[str, Any]) -> str:
    fields = SIGNATURE_FIELDS.get(collection)
    if fields:
        parts = [f"{field}={stable_value(row.get(field))}" for field in fields if field in row]
        return " | ".join(parts)
    return json.dumps(stable_value(row), ensure_ascii=False, sort_keys=True)


def semantic_counter(data: dict[str, Any], collection: str) -> Counter[str]:
    rows = data.get(collection, [])
    if not isinstance(rows, list):
        return Counter()
    return Counter(signature(collection, row) for row in rows if isinstance(row, dict))


def collection_rows(data: dict[str, Any], collection: str) -> list[dict[str, Any]]:
    rows = data.get(collection, [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def edge_key(row: dict[str, Any], include_step: bool = False) -> tuple[Any, ...]:
    base = (
        row.get("sourceAttributeNaturalKey"),
        row.get("sourceDatasetNaturalKey"),
        row.get("targetAttributeNaturalKey"),
        row.get("targetDatasetNaturalKey"),
    )
    if include_step:
        return base + (row.get("stepNaturalKey"),)
    return base


def is_attribute_sentinel(value: Any) -> bool:
    return isinstance(value, str) and (value in ATTRIBUTE_SENTINELS or value.endswith("|<*>"))


def dataset_edge_key(row: dict[str, Any], include_step: bool = False) -> tuple[Any, ...]:
    base = (row.get("sourceDatasetNaturalKey"), row.get("targetDatasetNaturalKey"))
    if include_step:
        return base + (row.get("stepNaturalKey"),)
    return base


def collect_contract_findings(data: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []

    for collection in COLLECTIONS:
        if collection not in data:
            findings.append(Finding("WARN", "missing_collection", f"Missing top-level collection: {collection}", {"collection": collection}))
            continue
        if not isinstance(data[collection], list):
            findings.append(Finding("ERROR", "invalid_collection", f"Collection is not a list: {collection}", {"collection": collection, "type": type(data[collection]).__name__}))

    datasets = {row.get("datasetNaturalKey") for row in collection_rows(data, "datasets")}
    attributes = {row.get("attributeNaturalKey") for row in collection_rows(data, "attributes")}
    steps = {row.get("stepNaturalKey") for row in collection_rows(data, "steps")}

    for collection, required_fields in REQUIRED_LINEAGE_FIELDS.items():
        for index, row in enumerate(collection_rows(data, collection)):
            missing = [field for field in required_fields if not row.get(field)]
            if missing:
                findings.append(Finding("ERROR", "missing_required_field", f"{collection}[{index}] is missing required fields", {"collection": collection, "index": index, "missing": missing}))
            if steps and row.get("stepNaturalKey") and row.get("stepNaturalKey") not in steps:
                findings.append(Finding("ERROR", "unknown_step_reference", f"{collection}[{index}] references an undeclared step", {"stepNaturalKey": row.get("stepNaturalKey")}))
            for field in ("sourceDatasetNaturalKey", "targetDatasetNaturalKey"):
                if datasets and row.get(field) and row.get(field) not in datasets:
                    findings.append(Finding("ERROR", "unknown_dataset_reference", f"{collection}[{index}] references an undeclared dataset", {"field": field, "value": row.get(field)}))
            for field in ("sourceAttributeNaturalKey", "targetAttributeNaturalKey"):
                if attributes and row.get(field) and is_attribute_sentinel(row.get(field)):
                    findings.append(Finding("WARN", "attribute_sentinel_reference", f"{collection}[{index}] uses a wildcard/sentinel attribute reference", {"field": field, "value": row.get(field)}))
                elif attributes and row.get(field) and row.get(field) not in attributes:
                    findings.append(Finding("ERROR", "unknown_attribute_reference", f"{collection}[{index}] references an undeclared attribute", {"field": field, "value": row.get(field)}))

    for collection in COLLECTIONS:
        counts = semantic_counter(data, collection)
        duplicates = [{"signature": sig, "count": count} for sig, count in counts.items() if count > 1]
        if duplicates:
            findings.append(Finding("WARN", "duplicate_semantic_records", f"{collection} has duplicate semantic records", {"collection": collection, "duplicates": duplicates[:20], "totalDuplicateSignatures": len(duplicates)}))

    tier1_edges = {edge_key(row) for row in collection_rows(data, "tier1QueryBlockAttributeLineage")}
    tier2_edges = {edge_key(row) for row in collection_rows(data, "tier2StatementAttributeLineage")}
    fact_edges = {edge_key(row) for row in collection_rows(data, "lineageFactAttribute")}
    tier3_edges = {dataset_edge_key(row) for row in collection_rows(data, "tier3DatasetLineage")}

    for edge in sorted(tier2_edges - tier1_edges):
        findings.append(Finding("WARN", "tier2_without_tier1_support", "Tier-2 attribute edge has no matching Tier-1 source/target evidence", {"edge": edge}))

    for edge in sorted(fact_edges - tier1_edges - tier2_edges):
        findings.append(Finding("WARN", "lineage_fact_without_tier_support", "LineageFact attribute edge has no matching Tier-1/Tier-2 evidence", {"edge": edge}))

    implied_dataset_edges = {
        (row.get("sourceDatasetNaturalKey"), row.get("targetDatasetNaturalKey"))
        for row in collection_rows(data, "tier2StatementAttributeLineage") + collection_rows(data, "lineageFactAttribute")
        if row.get("sourceDatasetNaturalKey") and row.get("targetDatasetNaturalKey")
    }
    for edge in sorted(implied_dataset_edges - tier3_edges):
        findings.append(Finding("WARN", "missing_tier3_rollup", "Attribute-level lineage implies a Tier-3 dataset edge that is not present", {"edge": edge}))

    return findings


def diff_expected_actual(expected: dict[str, Any], actual: dict[str, Any], max_examples: int) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for collection in COLLECTIONS:
        expected_counter = semantic_counter(expected, collection)
        actual_counter = semantic_counter(actual, collection)
        missing = list((expected_counter - actual_counter).elements())
        extra = list((actual_counter - expected_counter).elements())
        result[collection] = {
            "expected_count": sum(expected_counter.values()),
            "actual_count": sum(actual_counter.values()),
            "missing_count": len(missing),
            "extra_count": len(extra),
            "missing_examples": missing[:max_examples],
            "extra_examples": extra[:max_examples],
        }
    return result


def status_from(findings: list[Finding], diff: dict[str, Any] | None) -> str:
    has_error = any(f.severity == "ERROR" for f in findings)
    has_warn = any(f.severity == "WARN" for f in findings)
    has_diff = False
    if diff:
        has_diff = any(v["missing_count"] or v["extra_count"] for v in diff.values())
    if has_error or has_diff:
        return "FAIL"
    if has_warn:
        return "REVIEW"
    return "PASS"


def evidence_class(status: str, expected_path: Path | None) -> str:
    if expected_path and status == "PASS":
        return "APPROVED_GOLDEN_MATCH"
    if status == "FAIL":
        return "DETERMINISTIC_ISSUE"
    if expected_path:
        return "DETERMINISTIC_REVIEW"
    return "STRONG_EVIDENCE"


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Lineage Evaluation Report",
        "",
        f"- Status: `{report['status']}`",
        f"- Evidence class: `{report['evidence_class']}`",
        f"- Actual: `{report['actual_path']}`",
    ]
    if report.get("expected_path"):
        lines.append(f"- Expected: `{report['expected_path']}`")
    else:
        lines.append("- Expected: not provided; semantic correctness is not fully proven.")

    lines.extend(["", "## Collection counts", "", "| Collection | Count |", "|---|---:|"])
    for collection, count in report["actual_counts"].items():
        lines.append(f"| {collection} | {count} |")

    if report.get("diff"):
        lines.extend(["", "## Expected vs actual diff", "", "| Collection | Expected | Actual | Missing | Extra |", "|---|---:|---:|---:|---:|"])
        for collection, entry in report["diff"].items():
            lines.append(
                f"| {collection} | {entry['expected_count']} | {entry['actual_count']} | {entry['missing_count']} | {entry['extra_count']} |"
            )
        for collection, entry in report["diff"].items():
            if entry["missing_examples"] or entry["extra_examples"]:
                lines.extend(["", f"### {collection}"])
                for label in ("missing_examples", "extra_examples"):
                    if entry[label]:
                        lines.append(f"- {label.replace('_', ' ')}:")
                        for example in entry[label]:
                            lines.append(f"  - `{example}`")

    lines.extend(["", "## Contract findings"])
    if not report["findings"]:
        lines.append("")
        lines.append("No deterministic contract findings.")
    else:
        by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
        severity_counts = Counter(finding["severity"] for finding in report["findings"])
        category_counts = Counter(finding["category"] for finding in report["findings"])
        lines.extend(["", "### Summary", "", "| Severity | Count |", "|---|---:|"])
        for severity, count in severity_counts.most_common():
            lines.append(f"| {severity} | {count} |")
        lines.extend(["", "| Category | Count |", "|---|---:|"])
        for category, count in category_counts.most_common():
            lines.append(f"| {category} | {count} |")
        for finding in report["findings"]:
            by_category[finding["category"]].append(finding)
        max_findings = report.get("max_findings_per_category", 25)
        for category, findings in sorted(by_category.items()):
            lines.extend(["", f"### {category}", ""])
            if len(findings) > max_findings:
                lines.append(f"Showing first {max_findings} of {len(findings)} findings.")
                lines.append("")
            for finding in findings[:max_findings]:
                lines.append(f"- `{finding['severity']}`: {finding['message']}")
                if finding.get("evidence"):
                    compact = json.dumps(finding["evidence"], ensure_ascii=False, default=str)
                    lines.append(f"  - evidence: `{compact}`")

    lines.extend([
        "",
        "## AI/SME review note",
        "",
        "Do not treat no-golden results as approved lineage. Use this report to reduce manual review to the exceptions, then promote approved expected outputs into regression.",
    ])
    return "\n".join(lines) + "\n"


def build_report(actual_path: Path, expected_path: Path | None, max_examples: int, max_findings_per_category: int) -> dict[str, Any]:
    actual = load_json(actual_path)
    expected = load_json(expected_path) if expected_path else None
    findings = collect_contract_findings(actual)
    diff = diff_expected_actual(expected, actual, max_examples) if expected else None
    status = status_from(findings, diff)
    return {
        "status": status,
        "evidence_class": evidence_class(status, expected_path),
        "actual_path": str(actual_path),
        "expected_path": str(expected_path) if expected_path else None,
        "actual_counts": {collection: len(collection_rows(actual, collection)) for collection in COLLECTIONS},
        "findings": [asdict(finding) for finding in findings],
        "diff": diff,
        "max_findings_per_category": max_findings_per_category,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate DataDNA lineage JSON output.")
    parser.add_argument("--actual", required=True, type=Path, help="Actual parser lineage JSON")
    parser.add_argument("--expected", type=Path, help="Approved expected lineage JSON")
    parser.add_argument("--json-report", type=Path, help="Optional path to write machine-readable report")
    parser.add_argument("--markdown-report", type=Path, help="Optional path to write Markdown report")
    parser.add_argument("--max-examples", type=int, default=10, help="Max missing/extra examples per collection")
    parser.add_argument("--max-findings-per-category", type=int, default=25, help="Max findings per category shown in Markdown")
    parser.add_argument("--fail-on-review", action="store_true", help="Exit non-zero for REVIEW as well as FAIL")
    args = parser.parse_args()

    report = build_report(args.actual, args.expected, args.max_examples, args.max_findings_per_category)
    markdown = markdown_report(report)

    if args.json_report:
        args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if args.markdown_report:
        args.markdown_report.write_text(markdown, encoding="utf-8")

    print(markdown)
    if report["status"] == "FAIL":
        return 1
    if report["status"] == "REVIEW" and args.fail_on_review:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
