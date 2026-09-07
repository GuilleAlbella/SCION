#!/usr/bin/env python3
"""
SCION Test Runner
Validates SCION output across all test categories (Phase 1 + Phase 2):

  lineage       : BFS neighbourhood contains the expected object chain and edges
  changed       : object appears in the diff between two snapshots (MODIFIED)
  unchanged     : object does NOT appear in the diff (no recent changes)
  added         : object appears in the diff as newly ADDED
  dropped       : object appears in the diff as DROPPED / REMOVED
  usage         : object has PDCR query activity recorded in SCION
  impact        : object has at least one downstream node in the lineage graph
  criticality   : object has a criticality score computed (graph or usage based)
  diff_count    : snapshot diff produces at least N changes (smoke test for UC-03)
  breaking      : SCION classifies at least one change for the object as breaking
  exists        : object is present in the graph for the current snapshot
  absent        : object is NOT present in the graph (expected absence)
  snapshot_health : health + object count smoke test
  landscape     : Phase 2 — Landscape summary endpoint returns data (UC-15)
  reference     : Phase 2 — Reference org data (teams/applications) is loaded (UC-16)

Test file format (Object_*.txt):
    Object name  : <bare_name>
    Schema       : <optional – helps resolve when multiple schemas match>
    Priority     : P1 | P2 | P3 | P4  (default P3)
    Test type    : lineage | changed | unchanged | added | dropped | usage | impact
                   | criticality | diff_count | breaking | exists | absent | snapshot_health
                   | landscape | reference
    Lineage flow : A -> B -> C -> D   (lineage tests only)
    Min downstream : 1                (impact/diff_count/snapshot_health – default 1)
    Target field : total_objects      (landscape tests only – field to check)
    Min value    : 1                  (landscape/reference – minimum count)

Usage:
    python tests/run_tests.py
    python tests/run_tests.py --base-url http://ps-ubuntu-0043
    python tests/run_tests.py --base-url http://ps-ubuntu-0043 --snapshot 7
    python tests/run_tests.py --base-url http://ps-ubuntu-0043 --snapshot-from 6 --snapshot 7
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is required.  Run: pip install requests")
    sys.exit(1)

TESTS_DIR = Path(__file__).parent
RESULTS_DIR = TESTS_DIR / "results"
API = "/api/v1"

# ── Priority labels (for reporting) ──────────────────────────────────────────
PRIORITY_LABELS = {"P1": "Critical", "P2": "High", "P3": "Medium", "P4": "Low"}

# ── ANSI color constants ──────────────────────────────────────────────────────
_CLR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
GREEN  = "\033[32m"   if _CLR else ""
YELLOW = "\033[33m"   if _CLR else ""
RED    = "\033[31m"   if _CLR else ""
CYAN   = "\033[36m"   if _CLR else ""
BOLD   = "\033[1m"    if _CLR else ""
DIM    = "\033[2m"    if _CLR else ""
RESET  = "\033[0m"    if _CLR else ""


# ──────────────────────────────────────────────────────────────────────────────
# Parsing
# ──────────────────────────────────────────────────────────────────────────────

def parse_test_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")

    def field(key: str) -> str | None:
        m = re.search(rf"{key}\s*:\s*(.+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    object_name   = field("Object name") or path.stem
    test_type     = (field("Test type") or "lineage").lower()
    schema_name   = field("Schema")
    chain_raw     = field("Lineage flow")
    min_ds_raw    = field("Min downstream")
    chain         = [s.strip() for s in chain_raw.split("->")] if chain_raw else []
    min_downstream = int(min_ds_raw) if min_ds_raw and min_ds_raw.isdigit() else 1
    priority      = (field("Priority") or "P3").upper()
    target_field  = field("Target field")    # e.g. "total_objects" for landscape tests
    min_value_raw = field("Min value")
    min_value     = int(min_value_raw) if min_value_raw and min_value_raw.isdigit() else 0
    skip_raw  = field("Skip")
    skip      = skip_raw is not None and skip_raw.lower() in ("yes", "true", "1")
    snapshot_override_raw = field("Snapshot")
    snapshot_override = int(snapshot_override_raw) if snapshot_override_raw and snapshot_override_raw.strip().isdigit() else None

    return {
        "file":              path.name,
        "object_name":       object_name,
        "schema_name":       schema_name,
        "test_type":         test_type,
        "lineage_chain":     chain,
        "min_downstream":    min_downstream,
        "priority":          priority,
        "target_field":      target_field,
        "min_value":         min_value,
        "skip":              skip,
        "snapshot_override": snapshot_override,
    }


# ──────────────────────────────────────────────────────────────────────────────
# API helpers
# ──────────────────────────────────────────────────────────────────────────────

def api_get(base_url: str, path: str, timeout: int = 30, **params):
    url = base_url.rstrip("/") + API + path
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_snapshots(base_url: str) -> list:
    data = api_get(base_url, "/snapshots")
    snaps = data.get("snapshots", data) if isinstance(data, dict) else data
    return sorted(snaps, key=lambda s: int(s["snapshot_id"]))


def get_latest_snapshot(base_url: str) -> int:
    snaps = get_snapshots(base_url)
    if not snaps:
        raise RuntimeError("No snapshots found in SCION.")
    return int(snaps[-1]["snapshot_id"])


def get_snapshot_pair(base_url: str, from_arg: int | None, to_id: int) -> tuple[int, int]:
    snaps = get_snapshots(base_url)
    if len(snaps) < 2:
        raise RuntimeError("Need at least 2 snapshots for diff tests.")
    if from_arg:
        return from_arg, to_id
    # Use the snapshot just before to_id
    ids = [int(s["snapshot_id"]) for s in snaps]
    ids_before = [i for i in ids if i < to_id]
    if not ids_before:
        raise RuntimeError(f"No snapshot older than #{to_id} for diff comparison.")
    return max(ids_before), to_id


def resolve_object(base_url: str, snapshot_id: int, bare_name: str) -> list[str]:
    data = api_get(base_url, "/objects/search",
                   q=bare_name, snapshot_id=snapshot_id, source="graph", limit=10)
    items = data.get("items", data.get("results", []))
    return [r for r in items if bare_name.lower() in r.lower()]


def get_focus_graph(base_url: str, snapshot_id: int, root: str,
                    hops: int = 5, direction: str = "both") -> dict | None:
    try:
        return api_get(base_url, "/graph/focus",
                       snapshot_id=snapshot_id, root=root,
                       hops=hops, direction=direction, max_nodes=500)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return None
        raise


# ──────────────────────────────────────────────────────────────────────────────
# Result builder
# ──────────────────────────────────────────────────────────────────────────────

def _result(test: dict, status: str, error: str | None = None,
            note: str | None = None) -> dict:
    return {
        "file":        test["file"],
        "object_name": test["object_name"],
        "test_type":   test.get("test_type", "lineage"),
        "snapshot_id": None,
        "status":      status,
        "error":       error,
        "note":        note,
        "node_checks": [],
        "edge_checks": [],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Lineage test
# ──────────────────────────────────────────────────────────────────────────────

def run_lineage_test(base_url: str, snapshot_id: int, test: dict, hops: int) -> dict:
    chain = test["lineage_chain"]
    result = _result(test, "PASS")
    result["lineage_chain"] = " -> ".join(chain)

    if not chain:
        return _result(test, "SKIP", "No lineage chain defined in test file.")

    matches = resolve_object(base_url, snapshot_id, test["object_name"])
    if not matches:
        return _result(test, "FAIL",
                       f"Object '{test['object_name']}' not found in snapshot #{snapshot_id}.")

    # Narrow candidates to the hinted schema when one is provided, to avoid
    # picking the wrong schema instance when the same bare name exists in many schemas.
    schema_hint = test.get("schema_name")
    if schema_hint and len(matches) > 1:
        filtered = [m for m in matches if m.upper().startswith(schema_hint.upper() + ".")]
        if filtered:
            matches = filtered

    # When multiple schemas match, pick the root with the most chain coverage.
    # Tiebreaker: edge coverage (number of expected edges found).
    if len(matches) > 1:
        best_root, best_graph, best_nodes, best_edges = matches[0], None, -1, -1
        for candidate in matches:
            g = get_focus_graph(base_url, snapshot_id, candidate, hops=hops)
            if g is None:
                continue
            bare_ids: dict[str, list] = {}
            for n in g.get("nodes", []):
                b = n["object_name"].split(".")[-1].lower()
                bare_ids.setdefault(b, []).append(str(n["node_id"]))
            ep = {(str(e["source"]), str(e["target"])) for e in g.get("edges", [])}
            node_cov = sum(1 for obj in chain if obj.lower() in bare_ids)
            edge_cov = sum(
                1 for i in range(len(chain) - 1)
                if any((s, t) in ep
                       for s in bare_ids.get(chain[i].lower(), [])
                       for t in bare_ids.get(chain[i + 1].lower(), []))
            )
            if (node_cov, edge_cov) > (best_nodes, best_edges):
                best_root, best_graph, best_nodes, best_edges = candidate, g, node_cov, edge_cov
        root  = best_root
        graph = best_graph
        result["note"] = (f"Multiple matches {matches}; "
                          f"using '{root}' "
                          f"(nodes {best_nodes}/{len(chain)}, edges {best_edges}/{len(chain)-1})")
    else:
        root  = matches[0]
        graph = get_focus_graph(base_url, snapshot_id, root, hops=hops)

    if graph is None:
        return _result(test, "FAIL", f"Graph focus 404 for root='{root}'.")

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    bare_to_ids: dict[str, list] = {}
    for n in nodes:
        bare = n["object_name"].split(".")[-1].lower()
        bare_to_ids.setdefault(bare, []).append(str(n["node_id"]))

    edge_pairs: set[tuple] = {(str(e["source"]), str(e["target"])) for e in edges}

    for obj in chain:
        found_ids = bare_to_ids.get(obj.lower(), [])
        result["node_checks"].append({"object": obj, "found": bool(found_ids), "matched_ids": found_ids})

    for i in range(len(chain) - 1):
        src_ids = bare_to_ids.get(chain[i].lower(), [])
        tgt_ids = bare_to_ids.get(chain[i + 1].lower(), [])
        found   = any((s, t) in edge_pairs for s in src_ids for t in tgt_ids)
        result["edge_checks"].append({"source": chain[i], "target": chain[i + 1], "found": found})

    missing_nodes = [c for c in result["node_checks"] if not c["found"]]
    missing_edges = [c for c in result["edge_checks"] if not c["found"]]
    if missing_nodes or missing_edges:
        result["status"] = "FAIL" if missing_nodes else "PARTIAL"
        parts = []
        if missing_nodes:
            parts.append("Missing nodes: " + ", ".join(c["object"] for c in missing_nodes))
        if missing_edges:
            parts.append("Missing edges: " + ", ".join(
                f"{c['source']} -> {c['target']}" for c in missing_edges))
        result["error"] = "; ".join(parts)

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Diff tests (changed / unchanged / added / dropped)
# Uses /timeline so results cover the full snapshot history, not just one pair.
# ──────────────────────────────────────────────────────────────────────────────

def _classify_events(events: list) -> tuple[list, list, list]:
    """Split timeline events into (structural_mods, additions, removals).

    TABLE_ADDED/TABLE_REMOVED reflect snapshot coverage (object enters/leaves
    the extract) and are NOT the same as structural DDL changes.
    COLUMN_ADDED/COLUMN_REMOVED/COLUMN_MODIFIED and similar are structural.
    """
    structural, additions, removals = [], [], []
    # Change types that represent the whole object appearing or disappearing
    _TABLE_LEVEL_ADDS    = {"TABLE_ADDED", "TABLE_CREATED", "VIEW_ADDED", "VIEW_CREATED"}
    _TABLE_LEVEL_REMOVES = {"TABLE_REMOVED", "TABLE_DROPPED", "VIEW_REMOVED", "VIEW_DROPPED"}
    for e in events:
        ct = e["change_type"].upper()
        if ct in _TABLE_LEVEL_ADDS:
            additions.append(e)
        elif ct in _TABLE_LEVEL_REMOVES:
            removals.append(e)
        else:
            # COLUMN_ADDED, COLUMN_REMOVED, COLUMN_MODIFIED, COLUMN_POSITION_CHANGED,
            # INDEX_*, CONSTRAINT_*, TABLE_ALTERED, etc. → structural DDL change
            structural.append(e)
    return structural, additions, removals


def run_diff_test(base_url: str, snap_from: int, snap_to: int, test: dict) -> dict:
    """Check change history via /timeline (covers all snapshot pairs, not just one)."""
    test_type = test["test_type"]
    bare      = test["object_name"]
    result    = _result(test, "PASS")
    result["diff_source"] = "timeline (full history)"

    try:
        data = api_get(base_url, "/timeline", timeout=30,
                       object_name=bare, limit=200)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            # No timeline at all → object never appeared in any snapshot
            if test_type == "unchanged":
                result["note"] = "No timeline events found — object never changed (or not yet ingested)"
                return result
            return _result(test, "FAIL",
                           f"Timeline 404: '{bare}' has no history in SCION. "
                           "Object may not have been ingested.")
        raise

    events               = data.get("events", [])
    total                = data.get("total", 0)
    structural, adds, removes = _classify_events(events)
    all_types            = list(dict.fromkeys(e["change_type"] for e in events))  # deduped

    if test_type == "unchanged":
        if not structural:
            # TABLE_ADDED/TABLE_REMOVED are snapshot-coverage events (object enters/leaves
            # the extract), not DDL changes — they don't count as "changed".
            if adds or removes:
                result["note"] = (
                    f"Object appears/disappears across snapshots "
                    f"({len(adds)} TABLE_ADD + {len(removes)} TABLE_REMOVE) "
                    "but has no structural column/index changes (expected)"
                )
            else:
                result["note"] = "No change events in full history (expected)"
        else:
            result["status"] = "FAIL"
            result["error"]  = (
                f"Structural changes found ({len(structural)} event(s)): "
                f"{[e['change_type'] for e in structural[:5]]} "
                f"across snapshot(s) {sorted({e['snapshot_to'] for e in structural})[:5]}"
            )

    elif test_type == "changed":
        if structural:
            snap_ids = sorted({e["snapshot_to"] for e in structural})
            result["note"] = (f"{len(structural)} structural modification(s) "
                              f"({[e['change_type'] for e in structural[:3]]}) "
                              f"in snapshot(s) {snap_ids[:5]}")
        elif adds or removes:
            result["status"] = "PARTIAL"
            result["error"]  = (
                f"Object has history ({total} event(s): {all_types[:5]}) "
                "but no structural column modifications (COLUMN_ADDED/DROPPED/MODIFIED). "
                "Expected DDL-level change; only table-level ADD/REMOVE events found."
            )
        else:
            result["status"] = "FAIL"
            result["error"]  = ("No change events found in full snapshot history. "
                                "Object may not have been ingested in a comparable snapshot pair.")

    elif test_type == "added":
        if adds:
            snap_ids = sorted({e["snapshot_to"] for e in adds})
            result["note"] = (f"Found as '{adds[0]['change_type']}' "
                              f"in snapshot(s) {snap_ids[:3]}")
        elif structural or removes:
            result["status"] = "PARTIAL"
            result["error"]  = (f"Object has history but no TABLE_ADDED event: {all_types[:5]}")
        else:
            result["status"] = "FAIL"
            result["error"]  = ("No events found in full snapshot history. "
                                "Object may not have been ingested in any snapshot.")

    elif test_type == "dropped":
        if removes:
            snap_ids = sorted({e["snapshot_to"] for e in removes})
            result["note"] = (f"Found as '{removes[0]['change_type']}' "
                              f"in snapshot(s) {snap_ids[:3]}")
        elif structural or adds:
            result["status"] = "PARTIAL"
            result["error"]  = (f"Object has history but no removal event: {all_types[:5]}")
        else:
            result["status"] = "FAIL"
            result["error"]  = "No events found in full snapshot history."

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Usage test
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_usage(base_url: str, snapshot_id: int, qualified_name: str) -> dict | None:
    """Return usage API response if the object has data, else None."""
    try:
        data = api_get(base_url, f"/usage/object/{snapshot_id}", object=qualified_name)
    except requests.HTTPError:
        return None
    if not data.get("found"):
        return None
    usage = data.get("usage", {})
    if usage.get("has_data") and usage.get("query_count", 0) > 0:
        return data
    return None


def run_usage_test(base_url: str, snapshot_id: int, test: dict) -> dict:
    bare = test["object_name"]

    # Resolve on the primary snapshot first; fall back across all snapshots if needed.
    all_snaps      = get_snapshots(base_url)
    snap_ids_desc  = sorted([int(s["snapshot_id"]) for s in all_snaps], reverse=True)

    # Try to find the object and usage data — prefer snapshot_id, then others descending.
    ordered = [snapshot_id] + [s for s in snap_ids_desc if s != snapshot_id]

    found_snap = None
    qualified  = None
    usage_data = None

    schema_hint = test.get("schema_name")
    for sid in ordered:
        matches = resolve_object(base_url, sid, bare)
        if not matches:
            continue
        # Prefer the schema-hinted match when multiple schemas carry the same object name.
        if schema_hint and len(matches) > 1:
            filtered = [m for m in matches if m.upper().startswith(schema_hint.upper() + ".")]
            if filtered:
                matches = filtered
        root = matches[0]
        data = _fetch_usage(base_url, sid, root)
        if data:
            found_snap, qualified, usage_data = sid, root, data
            break
        if qualified is None:
            qualified = root  # remember first graph match even without usage

    result = _result(test, "PASS")

    if usage_data is None:
        if qualified is None:
            return _result(test, "FAIL",
                           f"Object '{bare}' not found in the graph for any snapshot. "
                           "It may not have been ingested.")
        return _result(test, "FAIL",
                       f"Object '{qualified}' exists in the graph but has no usage data "
                       f"in any of the {len(ordered)} available snapshot(s). "
                       "PDCR usage may not have been loaded yet "
                       "(check the Usage screen or run a usage ingest).")

    if found_snap != snapshot_id:
        result["note"] = (f"No usage in snapshot #{snapshot_id}; "
                          f"found data in snapshot #{found_snap} — using that.")
    result["snapshot_id"] = found_snap

    usage       = usage_data.get("usage", {})
    query_count = usage.get("query_count", 0)
    user_count  = usage.get("user_count", 0)
    last_access = usage.get("last_accessed")
    criticality = (usage_data.get("criticality") or {}).get("criticality_level")

    result["usage_detail"] = {
        "snapshot_used":     found_snap,
        "has_data":          True,
        "query_count":       query_count,
        "user_count":        user_count,
        "last_accessed":     last_access,
        "criticality_level": criticality,
    }
    note_prefix = result.get("note", "")
    result["note"] = ((note_prefix + " | ") if note_prefix else "") + (
        f"query_count={query_count}  users={user_count}  "
        f"last_accessed={last_access}  criticality={criticality}")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Impact test
# ──────────────────────────────────────────────────────────────────────────────

def _count_downstream(base_url: str, snapshot_id: int, root: str, hops: int) -> tuple[int, list, int]:
    """Returns (reachable_downstream_count, direct_downstream_names, total_nodes).

    reachable_downstream_count = all nodes in the downstream BFS subgraph minus the root itself.
    This measures total blast radius, not just the immediate next hop.
    """
    graph = get_focus_graph(base_url, snapshot_id, root, hops=hops, direction="down")
    if graph is None:
        return 0, [], 0
    nodes       = graph.get("nodes", [])
    edges       = graph.get("edges", [])
    feeds_edges = [e for e in edges if e.get("type") == "FEEDS"]
    root_bare   = root.split(".")[-1].lower()
    root_node   = next(
        (n for n in nodes if n["object_name"].split(".")[-1].lower() == root_bare), None
    )
    if not root_node:
        # root not in result — count everything as downstream
        return max(0, len(nodes) - 1), [n["object_name"] for n in nodes[:5]], len(nodes)
    root_id = str(root_node["node_id"])
    # Direct downstream (1 hop) — for display only
    direct_ids   = {str(e["target"]) for e in feeds_edges if str(e["source"]) == root_id}
    direct_names = [n["object_name"] for n in nodes if str(n["node_id"]) in direct_ids]
    # Reachable downstream = entire subgraph minus the root
    reachable    = len(nodes) - 1
    return reachable, direct_names, len(nodes)


def run_impact_test(base_url: str, snapshot_id: int, test: dict, hops: int) -> dict:
    matches = resolve_object(base_url, snapshot_id, test["object_name"])
    if not matches:
        return _result(test, "FAIL",
                       f"Object '{test['object_name']}' not found in snapshot #{snapshot_id}.")

    result = _result(test, "PASS")

    # When multiple schemas match, evaluate all and pick the one with the most downstream.
    # This avoids silently using a low-connectivity schema instance.
    if len(matches) > 1:
        best_root, best_count, best_names, best_total = None, -1, [], 0
        all_counts = {}
        for candidate in matches:
            cnt, names, total = _count_downstream(base_url, snapshot_id, candidate, hops)
            all_counts[candidate] = cnt
            if cnt > best_count:
                best_root, best_count, best_names, best_total = candidate, cnt, names, total
        root = best_root
        result["note"] = (f"Multiple matches {list(all_counts.keys())}; "
                          f"using '{root}' (most downstream: {best_count})")
        downstream_count = best_count
        downstream_names = best_names
        total_nodes      = best_total
    else:
        root = matches[0]
        downstream_count, downstream_names, total_nodes = _count_downstream(
            base_url, snapshot_id, root, hops)

    result["impact_detail"] = {
        "root":                    root,
        "direct_downstream_count": downstream_count,
        "total_subgraph_nodes":    total_nodes,
        "direct_downstream":       downstream_names,
    }

    min_ds = test.get("min_downstream", 1)
    if downstream_count >= min_ds:
        note_prefix = result.get("note", "")
        result["note"] = ((note_prefix + " | ") if note_prefix else "") + (
            f"{downstream_count} direct downstream node(s): {downstream_names[:5]}")
    else:
        result["status"] = "FAIL"
        result["error"]  = (f"Expected >={min_ds} downstream node(s) "
                            f"but found {downstream_count}. "
                            f"Total subgraph: {total_nodes} node(s).")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Breaking-change test
# ──────────────────────────────────────────────────────────────────────────────

def run_breaking_test(base_url: str, test: dict) -> dict:
    """Verify that SCION classifies at least one change for this object as breaking."""
    bare   = test["object_name"]
    min_br = test.get("min_downstream", 1)  # reuse field as min_breaking_events
    result = _result(test, "PASS")

    try:
        data = api_get(base_url, "/timeline", timeout=30, object_name=bare, limit=200)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return _result(test, "FAIL",
                           f"No timeline history for '{bare}'. Object may not be ingested.")
        raise

    events   = data.get("events", [])
    breaking = [e for e in events if e.get("is_breaking") is True]
    total    = data.get("total", 0)

    result["breaking_detail"] = {
        "total_events":    total,
        "breaking_events": len(breaking),
        "breaking_types":  list(dict.fromkeys(e["change_type"] for e in breaking)),
        "breaking_snaps":  sorted({e["snapshot_to"] for e in breaking}),
    }

    if len(breaking) >= min_br:
        result["note"] = (f"{len(breaking)} breaking event(s) out of {total} total: "
                          f"{list(dict.fromkeys(e['change_type'] for e in breaking))[:5]} "
                          f"in snapshot(s) {sorted({e['snapshot_to'] for e in breaking})[:5]}")
    elif total == 0:
        result["status"] = "FAIL"
        result["error"]  = f"No timeline events found for '{bare}'. Object may not be ingested."
    else:
        result["status"] = "FAIL"
        result["error"]  = (f"No breaking changes detected out of {total} event(s). "
                            "SCION may not have flagged any change as breaking for this object.")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Exists / absent tests
# ──────────────────────────────────────────────────────────────────────────────

def run_exists_test(base_url: str, snapshot_id: int, test: dict) -> dict:
    """Object MUST be found in the graph for the given snapshot."""
    bare    = test["object_name"]
    matches = resolve_object(base_url, snapshot_id, bare)
    result  = _result(test, "PASS")
    if matches:
        result["note"] = f"Found as: {matches[:3]}"
    else:
        result["status"] = "FAIL"
        result["error"]  = (f"Object '{bare}' not found in snapshot #{snapshot_id}. "
                            "It may not have been ingested.")
    return result


def run_absent_test(base_url: str, snapshot_id: int, test: dict) -> dict:
    """Object MUST NOT be found in the graph for the given snapshot."""
    bare    = test["object_name"]
    matches = resolve_object(base_url, snapshot_id, bare)
    result  = _result(test, "PASS")
    if not matches:
        result["note"] = f"Correctly absent from snapshot #{snapshot_id}"
    else:
        result["status"] = "FAIL"
        result["error"]  = (f"Object '{bare}' was found in snapshot #{snapshot_id} "
                            f"but expected to be absent: {matches[:3]}")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Snapshot health test
# ──────────────────────────────────────────────────────────────────────────────

def run_snapshot_health_test(base_url: str, snapshot_id: int, test: dict) -> dict:
    """Check SCION health + snapshot metrics in one pass."""
    min_objects = test.get("min_downstream", 100)   # reuse as min_objects threshold
    result      = _result(test, "PASS")
    checks      = []
    failed      = []

    # ── 1. Readiness probe ──
    try:
        health = api_get(base_url, "/health/ready", timeout=10)
        status = health.get("status", "").lower()
        db_ok  = health.get("database", {}).get("status", "").lower() in ("ok", "healthy", "ready")
        if status in ("ok", "ready", "healthy") or db_ok:
            checks.append("health=ready")
        else:
            checks.append(f"health={status}")
            failed.append(f"SCION not ready: {status}")
    except Exception as e:
        checks.append("health=ERROR")
        failed.append(f"Health endpoint error: {e}")

    # ── 2. Snapshot metrics ──
    try:
        metrics = api_get(base_url, f"/metrics/snapshot/{snapshot_id}", timeout=15)
        # Try common field names for object count
        obj_count = (metrics.get("table_count") or metrics.get("object_count") or
                     metrics.get("node_count") or metrics.get("total_objects") or
                     sum(v for k, v in metrics.items() if isinstance(v, int) and k != "snapshot_id"))
        checks.append(f"objects={obj_count}")
        if isinstance(obj_count, int) and obj_count >= min_objects:
            pass  # good
        elif isinstance(obj_count, int):
            failed.append(f"Only {obj_count} objects in snapshot #{snapshot_id} "
                          f"(expected >={min_objects})")
        result["snapshot_metrics"] = metrics
    except requests.HTTPError as e:
        checks.append("metrics=ERROR")
        failed.append(f"Metrics endpoint error: {e.response.status_code}")
    except Exception as e:
        checks.append("metrics=ERROR")
        failed.append(f"Metrics error: {e}")

    result["health_checks"] = checks
    if failed:
        result["status"] = "FAIL"
        result["error"]  = "; ".join(failed)
    else:
        result["note"] = "  ".join(checks)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Criticality test  (UC-14)
# ──────────────────────────────────────────────────────────────────────────────

def run_criticality_test(base_url: str, snapshot_id: int, test: dict) -> dict:
    """Verify that SCION has computed a criticality score for this object."""
    bare = test["object_name"]

    all_snaps     = get_snapshots(base_url)
    snap_ids_desc = sorted([int(s["snapshot_id"]) for s in all_snaps], reverse=True)
    ordered       = [snapshot_id] + [s for s in snap_ids_desc if s != snapshot_id]

    found_snap        = None
    qualified         = None
    criticality_level = None
    combined = graph_score = usage_score = 0.0

    for sid in ordered:
        matches = resolve_object(base_url, sid, bare)
        if not matches:
            continue
        root = matches[0]
        try:
            data = api_get(base_url, f"/usage/object/{sid}", object=root)
        except requests.HTTPError:
            continue
        if data.get("found") and data.get("criticality"):
            crit = data["criticality"]
            if crit.get("criticality_level"):
                found_snap        = sid
                qualified         = root
                criticality_level = crit["criticality_level"]
                combined          = crit.get("combined_score", 0.0)
                graph_score       = crit.get("graph_score", 0.0)
                usage_score       = crit.get("usage_score", 0.0)
                break
        if qualified is None and data.get("found"):
            qualified = root

    result = _result(test, "PASS")

    if criticality_level is None:
        if qualified is None:
            return _result(test, "FAIL",
                           f"Object '{bare}' not found in the graph for any snapshot.")
        return _result(test, "FAIL",
                       f"Object '{qualified}' found in graph but criticality_level is null "
                       "in all snapshots. Criticality may not have been computed yet.")

    if found_snap != snapshot_id:
        result["note"] = f"No criticality in snapshot #{snapshot_id}; found in snapshot #{found_snap}"
    result["snapshot_id"] = found_snap
    result["criticality_detail"] = {
        "snapshot_used":    found_snap,
        "criticality_level": criticality_level,
        "combined_score":   combined,
        "graph_score":      graph_score,
        "usage_score":      usage_score,
    }
    prefix = result.get("note", "")
    result["note"] = ((prefix + " | ") if prefix else "") + (
        f"criticality_level={criticality_level}  "
        f"graph_score={graph_score:.3f}  usage_score={usage_score:.3f}  combined={combined:.3f}")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Diff-count test  (UC-03)
# ──────────────────────────────────────────────────────────────────────────────

def run_diff_count_test(base_url: str, snap_from: int, snap_to: int, test: dict) -> dict:
    """Verify that a snapshot diff returns at least min_changes rows (UC-03)."""
    min_changes = test.get("min_downstream", 10)
    result      = _result(test, "PASS")

    try:
        data = api_get(base_url, "/changes", timeout=90,
                       snapshot_from=snap_from, snapshot_to=snap_to, limit=500)
    except requests.Timeout:
        return _result(test, "SKIP",
                       f"Diff #{snap_from}→#{snap_to} timed out. "
                       "Trigger the diff in the UI first, then re-run.")
    except requests.HTTPError as e:
        return _result(test, "FAIL",
                       f"Changes endpoint error: {e.response.status_code}")

    changes      = data.get("changes", [])
    count        = len(changes)
    sample_types = list(dict.fromkeys(c["change_type"] for c in changes[:20]))

    result["diff_count_detail"] = {
        "snapshot_from":    snap_from,
        "snapshot_to":      snap_to,
        "changes_returned": count,
        "sample_types":     sample_types,
    }

    if count >= min_changes:
        result["note"] = (f"Diff #{snap_from}→#{snap_to}: {count} change(s) returned  "
                          f"types: {sample_types[:5]}")
    else:
        result["status"] = "FAIL"
        result["error"]  = (f"Expected >={min_changes} changes in diff #{snap_from}→#{snap_to} "
                            f"but got {count}. Diff may not have been computed yet.")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Landscape test  (Phase 2 — UC-15)
# ──────────────────────────────────────────────────────────────────────────────

def run_landscape_test(base_url: str, snapshot_id: int, test: dict) -> dict:
    """Verify that the Landscape summary endpoint returns populated data."""
    result = _result(test, "PASS")
    target_field = test.get("target_field") or "total_objects"
    min_value    = test.get("min_value", 1)

    try:
        data = api_get(base_url, "/landscape/summary", snapshot_id=snapshot_id, timeout=30)
    except requests.HTTPError as e:
        return _result(test, "FAIL",
                       f"Landscape summary endpoint error: {e.response.status_code}. "
                       "Landscape may not be enabled or the snapshot has no data.")
    except Exception as e:
        return _result(test, "FAIL", f"Landscape endpoint unreachable: {e}")

    # The summary endpoint may use different field names across versions.
    # Try the caller-specified field first, then fall back to known alternatives.
    _COUNT_CANDIDATES = [
        target_field,
        "high_risk_count", "entity_count", "active_entity_count",
        "total_objects", "total_schemas", "object_count", "node_count",
    ]
    value = None
    used_field = target_field
    for candidate in _COUNT_CANDIDATES:
        v = data.get(candidate)
        if v is not None and isinstance(v, (int, float)) and v > 0:
            value, used_field = v, candidate
            break
    # Fallback: count top_risk_objects if present
    if value is None or value == 0:
        top_risk = data.get("top_risk_objects")
        if isinstance(top_risk, list) and len(top_risk) > 0:
            value, used_field = len(top_risk), "top_risk_objects (count)"

    entity_count   = data.get("entity_count") or data.get("total_objects") or value or 0
    high_risk      = data.get("high_risk_count") or data.get("high_risk_objects") or 0
    recent_changes = data.get("recent_changes_count", 0)

    result["landscape_detail"] = {
        "snapshot_id":    snapshot_id,
        "entity_count":   entity_count,
        "high_risk":      high_risk,
        "recent_changes": recent_changes,
        "checked_field":  used_field,
        "field_value":    value,
        "all_keys":       list(data.keys()),
    }

    if value is None:
        result["status"] = "FAIL"
        result["error"]  = (f"No numeric count field found in landscape/summary response. "
                            f"Got keys: {list(data.keys())[:10]}")
    elif value < min_value:
        result["status"] = "FAIL"
        result["error"]  = (f"Landscape '{used_field}' = {value} < min {min_value}. "
                            "Snapshot may be empty or landscape not yet computed.")
    else:
        result["note"] = (f"{used_field}={value}  high_risk={high_risk}  "
                          f"recent_changes={recent_changes}")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Reference data test  (Phase 2 — UC-16)
# ──────────────────────────────────────────────────────────────────────────────

def run_reference_test(base_url: str, test: dict) -> dict:
    """Verify that reference data (teams or applications) has been loaded."""
    result   = _result(test, "PASS")
    # object_name doubles as the sub-resource: "teams" or "applications"
    resource = test.get("object_name", "teams").lower()
    if resource not in ("teams", "applications"):
        resource = "teams"
    min_count = test.get("min_value", 1)

    try:
        data = api_get(base_url, f"/reference/{resource}", timeout=15)
    except requests.HTTPError as e:
        return _result(test, "FAIL",
                       f"Reference /{resource} endpoint error: {e.response.status_code}. "
                       "Reference data may not have been uploaded yet.")
    except Exception as e:
        return _result(test, "FAIL", f"Reference endpoint unreachable: {e}")

    items = (data.get(resource) or data.get("items") or
             data if isinstance(data, list) else [])
    count = len(items)

    result["reference_detail"] = {
        "resource": resource,
        "count":    count,
        "sample":   [str(i.get("name", i)) for i in items[:3]] if items else [],
    }

    if count >= min_count:
        result["note"] = f"{resource}: {count} record(s) found  sample={result['reference_detail']['sample']}"
    else:
        result["status"] = "FAIL"
        result["error"]  = (f"Expected >={min_count} {resource} but found {count}. "
                            "Upload org-hierarchy CSV via the Reference page first.")
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Dispatcher
# ──────────────────────────────────────────────────────────────────────────────

def run_test(base_url: str, snapshot_id: int, snap_from: int, snap_to: int,
             test: dict, hops: int) -> dict:
    effective_snapshot = test.get("snapshot_override") or snapshot_id
    if test.get("skip"):
        r = _result(test, "SKIP", note="Pending setup — see fixture file Note for details.")
        r["snapshot_id"] = snapshot_id
        r["priority"]    = test.get("priority", "P3")
        return r
    test_type = test.get("test_type", "lineage")
    if test_type == "lineage":
        r = run_lineage_test(base_url, effective_snapshot, test, hops)
    elif test_type in ("changed", "unchanged", "added", "dropped"):
        r = run_diff_test(base_url, snap_from, snap_to, test)
    elif test_type == "usage":
        r = run_usage_test(base_url, effective_snapshot, test)
    elif test_type == "impact":
        r = run_impact_test(base_url, effective_snapshot, test, hops)
    elif test_type == "breaking":
        r = run_breaking_test(base_url, test)
    elif test_type == "exists":
        r = run_exists_test(base_url, effective_snapshot, test)
    elif test_type == "absent":
        r = run_absent_test(base_url, effective_snapshot, test)
    elif test_type == "snapshot_health":
        r = run_snapshot_health_test(base_url, effective_snapshot, test)
    elif test_type == "criticality":
        r = run_criticality_test(base_url, effective_snapshot, test)
    elif test_type == "diff_count":
        r = run_diff_count_test(base_url, snap_from, snap_to, test)
    elif test_type == "landscape":
        r = run_landscape_test(base_url, effective_snapshot, test)
    elif test_type == "reference":
        r = run_reference_test(base_url, test)
    else:
        r = _result(test, "SKIP", f"Unknown test type '{test_type}'.")
    r["snapshot_id"] = effective_snapshot
    r["priority"]    = test.get("priority", "P3")
    return r


# ──────────────────────────────────────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────────────────────────────────────

def export(results: list, out_base: Path) -> tuple[Path, Path]:
    out_base.parent.mkdir(parents=True, exist_ok=True)

    summary = {
        "run_at":  datetime.now().isoformat(),
        "total":   len(results),
        "passed":  sum(1 for r in results if r["status"] == "PASS"),
        "partial": sum(1 for r in results if r["status"] == "PARTIAL"),
        "failed":  sum(1 for r in results if r["status"] == "FAIL"),
        "skipped": sum(1 for r in results if r["status"] == "SKIP"),
        "tests":   results,
    }
    json_path = out_base.with_suffix(".json")
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    csv_path = out_base.with_suffix(".csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["File", "Object", "Type", "Priority", "Snapshot", "Status",
                    "Detail", "Nodes missing", "Edges missing", "Note", "Error"])
        for r in results:
            nodes_miss = "; ".join(
                c["object"] for c in r.get("node_checks", []) if not c["found"])
            edges_miss = "; ".join(
                f"{c['source']} -> {c['target']}"
                for c in r.get("edge_checks", []) if not c["found"])
            detail = (r.get("lineage_chain") or
                      r.get("diff_pair") or
                      (str(r.get("usage_detail", {}).get("query_count", "")) + " queries"
                       if r.get("usage_detail") else "") or
                      (str(r.get("impact_detail", {}).get("direct_downstream_count", "")) + " downstream"
                       if r.get("impact_detail") else "") or "")
            w.writerow([r["file"], r["object_name"], r.get("test_type", "lineage"),
                        r.get("priority", "P3"), r.get("snapshot_id", ""), r["status"],
                        detail, nodes_miss, edges_miss,
                        r.get("note", ""), r.get("error", "")])

    return json_path, csv_path


# ──────────────────────────────────────────────────────────────────────────────
# HTML report generation
# ──────────────────────────────────────────────────────────────────────────────

def _detail_html(r: dict) -> str:
    """Render a per-test detail line as HTML."""
    tt = r.get("test_type", "")

    if tt == "lineage":
        ncs = r.get("node_checks", [])
        if not ncs:
            return ""
        parts = []
        for i, nc in enumerate(ncs):
            tick = "✓" if nc["found"] else "✗"
            cls  = "ok" if nc["found"] else "bad"
            parts.append(f'<span class="{cls}">{tick}</span>&nbsp;<code>{nc["object"]}</code>')
            if i < len(ncs) - 1:
                ec = r.get("edge_checks", [{}] * len(ncs))
                edge_ok = ec[i]["found"] if i < len(ec) else True
                arrow_cls = "ok" if edge_ok else "bad"
                parts.append(f'<span class="{arrow_cls}">──▶</span>')
        return '<div class="detail chain">' + " ".join(parts) + "</div>"

    if tt == "impact":
        d = r.get("impact_detail", {})
        cnt = d.get("direct_downstream_count", 0)
        direct = d.get("direct_downstream", [])
        sample = ", ".join(str(x).split(".")[-1] for x in direct[:3])
        return (f'<div class="detail">💥 Blast radius: <strong>{cnt}</strong> downstream objects'
                + (f'  <span class="dim">(direct: {sample})</span>' if sample else "")
                + "</div>")

    if tt == "usage":
        d = r.get("usage_detail", {})
        qc  = f"{d.get('query_count', 0):,}"
        uc  = d.get("user_count", 0)
        la  = d.get("last_accessed", "—")
        crit = d.get("criticality_level", "—")
        return (f'<div class="detail">📊 <strong>{qc}</strong> queries  ·  '
                f'<strong>{uc}</strong> users  ·  last: {la}  ·  '
                f'criticality: <strong>{crit}</strong></div>')

    if tt == "criticality":
        d = r.get("criticality_detail", {})
        lvl = d.get("criticality_level", "—")
        g   = d.get("graph_score", 0)
        u   = d.get("usage_score", 0)
        c   = d.get("combined_score", 0)
        return (f'<div class="detail">⭐ Level: <strong>{lvl}</strong>  |  '
                f'graph={g:.3f}  usage={u:.3f}  combined={c:.3f}</div>')

    if tt == "diff_count":
        d = r.get("diff_count_detail", {})
        cnt  = d.get("changes_returned", 0)
        sfr  = d.get("snapshot_from", "?")
        sto  = d.get("snapshot_to", "?")
        typs = ", ".join(d.get("sample_types", [])[:5])
        return (f'<div class="detail">🔍 <strong>{cnt:,}</strong> changes across '
                f'snapshot #{sfr} → #{sto}  |  types: {typs}</div>')

    if tt == "breaking":
        d = r.get("breaking_detail", {})
        bc   = d.get("breaking_events", 0)
        typs = ", ".join(d.get("breaking_types", [])[:4])
        snps = str(d.get("breaking_snaps", []))
        return (f'<div class="detail">⚡ <strong>{bc}</strong> breaking change(s) detected: '
                f'{typs}  in snapshots {snps}</div>')

    if tt == "snapshot_health":
        checks = "  ·  ".join(r.get("health_checks", []))
        return f'<div class="detail">🏥 {checks}  ·  all checks passed</div>'

    if tt == "landscape":
        d = r.get("landscape_detail", {})
        hr  = d.get("high_risk", 0)
        ec  = d.get("entity_count", 0)
        rc  = d.get("recent_changes", 0)
        return (f'<div class="detail">🗺 high_risk_count=<strong>{hr}</strong>  ·  '
                f'entity_count=<strong>{ec:,}</strong>  ·  '
                f'recent_changes=<strong>{rc:,}</strong></div>')

    if tt == "reference":
        d = r.get("reference_detail", {})
        res  = d.get("resource", "")
        cnt  = d.get("count", 0)
        samp = ", ".join(d.get("sample", [])[:3])
        return (f'<div class="detail">📋 {res}: <strong>{cnt}</strong> records'
                + (f'  ·  sample: [{samp}]' if samp else "") + "</div>")

    # changed / unchanged / added / dropped — show note
    note = r.get("note") or ""
    if note:
        return f'<div class="detail dim">{note}</div>'
    return ""


def export_html(results: list, out_path: Path,
                snapshot_id: int, snap_from: int, snap_to: int,
                base_url: str, elapsed: float) -> Path:
    """Generate a self-contained HTML test report."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    run_at   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total    = len(results)
    passed   = sum(1 for r in results if r["status"] == "PASS")
    partial  = sum(1 for r in results if r["status"] == "PARTIAL")
    failed   = sum(1 for r in results if r["status"] == "FAIL")
    skipped  = sum(1 for r in results if r["status"] == "SKIP")
    pass_pct = round(passed / total * 100) if total else 0

    # Group by test type
    by_type: dict[str, list] = {}
    for r in results:
        by_type.setdefault(r.get("test_type", "lineage"), []).append(r)

    # Build rows
    rows_html = []
    for ttype, tresults in sorted(by_type.items()):
        rows_html.append(
            f'<tr class="group-header"><td colspan="5">{ttype.upper()}</td></tr>'
        )
        for r in tresults:
            status = r["status"]
            badge_cls = {"PASS": "badge-pass", "FAIL": "badge-fail",
                         "PARTIAL": "badge-partial", "SKIP": "badge-skip"}.get(status, "")
            detail_html = _detail_html(r)
            elapsed_r   = r.get("elapsed", "")
            elapsed_str = f"{elapsed_r:.1f}s" if isinstance(elapsed_r, float) else ""
            note_html   = ""
            if r.get("error"):
                note_html = f'<div class="error-msg">✗ {r["error"]}</div>'
            rows_html.append(f"""
            <tr>
              <td><code>{r['object_name']}</code></td>
              <td><span class="priority">{r.get('priority','P3')}</span></td>
              <td>{detail_html}{note_html}</td>
              <td class="time">{elapsed_str}</td>
              <td><span class="badge {badge_cls}">{status}</span></td>
            </tr>""")

    rows_joined = "\n".join(rows_html)

    # Summary table by type
    sum_rows = []
    for ttype, tresults in sorted(by_type.items()):
        p  = sum(1 for r in tresults if r["status"] == "PASS")
        pa = sum(1 for r in tresults if r["status"] == "PARTIAL")
        f  = sum(1 for r in tresults if r["status"] == "FAIL")
        s  = sum(1 for r in tresults if r["status"] == "SKIP")
        tot = p + pa + f + s
        sum_rows.append(f"""
        <tr>
          <td>{ttype}</td>
          <td>{tot}</td>
          <td class="c-pass">{p if p else ''}</td>
          <td class="c-partial">{pa if pa else ''}</td>
          <td class="c-fail">{f if f else ''}</td>
          <td class="c-skip">{s if s else ''}</td>
        </tr>""")
    sum_rows_joined = "\n".join(sum_rows)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SCION Validation Report · {run_at}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 14px;
    background: #0f1117;
    color: #e2e8f0;
    line-height: 1.5;
  }}
  a {{ color: #63b3ed; }}

  /* ── Header ── */
  .header {{
    background: linear-gradient(135deg, #1a1f36 0%, #0d1b2e 100%);
    border-bottom: 2px solid #2d3a55;
    padding: 28px 40px 22px;
  }}
  .header h1 {{
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.5px;
    color: #fff;
  }}
  .header h1 span {{ color: #63b3ed; }}
  .header .meta {{
    margin-top: 6px;
    color: #94a3b8;
    font-size: 13px;
  }}
  .header .meta b {{ color: #cbd5e1; }}

  /* ── Stats row ── */
  .stats {{
    display: flex;
    gap: 16px;
    padding: 20px 40px;
    background: #141820;
    border-bottom: 1px solid #1e2535;
    flex-wrap: wrap;
  }}
  .stat-card {{
    background: #1e2535;
    border-radius: 10px;
    padding: 14px 22px;
    min-width: 110px;
    text-align: center;
  }}
  .stat-card .num {{
    font-size: 32px;
    font-weight: 700;
    line-height: 1;
  }}
  .stat-card .lbl {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: #64748b;
    margin-top: 4px;
  }}
  .num-pass    {{ color: #4ade80; }}
  .num-fail    {{ color: #f87171; }}
  .num-partial {{ color: #fbbf24; }}
  .num-skip    {{ color: #64748b; }}
  .num-pct     {{ color: #60a5fa; }}
  .num-total   {{ color: #e2e8f0; }}

  /* ── Summary table ── */
  .section {{ padding: 24px 40px; }}
  .section h2 {{ font-size: 14px; font-weight: 600; text-transform: uppercase;
                 letter-spacing: 0.8px; color: #64748b; margin-bottom: 12px; }}

  .sum-table, .results-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  .sum-table th, .results-table th {{
    background: #1e2535;
    color: #94a3b8;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.6px;
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid #2d3a55;
  }}
  .sum-table td, .results-table td {{
    padding: 8px 12px;
    border-bottom: 1px solid #1a2030;
    vertical-align: top;
  }}
  .sum-table tr:hover td, .results-table tr:hover td {{
    background: #1a2233;
  }}
  .c-pass    {{ color: #4ade80; font-weight: 600; }}
  .c-fail    {{ color: #f87171; font-weight: 600; }}
  .c-partial {{ color: #fbbf24; font-weight: 600; }}
  .c-skip    {{ color: #64748b; }}
  .sum-table tfoot td {{
    font-weight: 700;
    border-top: 2px solid #2d3a55;
    color: #e2e8f0;
  }}

  /* ── Results table ── */
  .group-header td {{
    background: #1a2030;
    color: #60a5fa;
    font-weight: 700;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 6px 12px;
    border-top: 1px solid #2d3a55;
  }}
  .badge {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
  }}
  .badge-pass    {{ background: #14532d; color: #4ade80; }}
  .badge-fail    {{ background: #450a0a; color: #f87171; }}
  .badge-partial {{ background: #451a03; color: #fbbf24; }}
  .badge-skip    {{ background: #1e2535; color: #64748b; }}
  .priority {{
    display: inline-block;
    padding: 1px 7px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 600;
    background: #1e2535;
    color: #94a3b8;
  }}
  .detail {{ color: #cbd5e1; margin-top: 4px; font-size: 12px; line-height: 1.6; }}
  .detail.chain {{ font-size: 12px; }}
  .detail code {{ background: #1a2030; padding: 1px 5px; border-radius: 3px;
                  font-family: "Cascadia Code", "Fira Code", monospace; font-size: 11px; }}
  .ok   {{ color: #4ade80; }}
  .bad  {{ color: #f87171; }}
  .dim  {{ color: #64748b; }}
  .error-msg {{ color: #f87171; font-size: 12px; margin-top: 4px; }}
  .time {{ color: #475569; font-size: 12px; white-space: nowrap; }}

  /* ── Footer ── */
  .footer {{
    padding: 20px 40px;
    color: #334155;
    font-size: 12px;
    border-top: 1px solid #1a2030;
    margin-top: 16px;
  }}
</style>
</head>
<body>

<div class="header">
  <h1><span>SCION</span> · Automated Validation Suite</h1>
  <div class="meta">
    <b>{run_at}</b> &nbsp;·&nbsp;
    Phase 1 + Phase 2 · PDCR · Lineage · Changes &nbsp;·&nbsp;
    Server: <b>{base_url}</b> &nbsp;·&nbsp;
    Snapshot: <b>#{snapshot_id}</b> &nbsp;·&nbsp;
    Diff: <b>#{snap_from}→#{snap_to}</b> &nbsp;·&nbsp;
    Total time: <b>{elapsed:.1f}s</b>
  </div>
</div>

<div class="stats">
  <div class="stat-card">
    <div class="num num-total">{total}</div>
    <div class="lbl">Tests</div>
  </div>
  <div class="stat-card">
    <div class="num num-pct">{pass_pct}%</div>
    <div class="lbl">Pass rate</div>
  </div>
  <div class="stat-card">
    <div class="num num-pass">{passed}</div>
    <div class="lbl">Pass</div>
  </div>
  <div class="stat-card">
    <div class="num num-partial">{partial}</div>
    <div class="lbl">Partial</div>
  </div>
  <div class="stat-card">
    <div class="num num-fail">{failed}</div>
    <div class="lbl">Fail</div>
  </div>
  <div class="stat-card">
    <div class="num num-skip">{skipped}</div>
    <div class="lbl">Skip</div>
  </div>
</div>

<div class="section">
  <h2>By Test Category</h2>
  <table class="sum-table">
    <thead>
      <tr>
        <th>Category</th><th>Total</th>
        <th>Pass</th><th>Partial</th><th>Fail</th><th>Skip</th>
      </tr>
    </thead>
    <tbody>
      {sum_rows_joined}
    </tbody>
    <tfoot>
      <tr>
        <td>TOTAL</td>
        <td>{total}</td>
        <td class="c-pass">{passed}</td>
        <td class="c-partial">{partial if partial else ''}</td>
        <td class="c-fail">{failed if failed else ''}</td>
        <td class="c-skip">{skipped if skipped else ''}</td>
      </tr>
    </tfoot>
  </table>
</div>

<div class="section">
  <h2>All Test Results</h2>
  <table class="results-table">
    <thead>
      <tr>
        <th>Object</th><th>Priority</th>
        <th>Detail</th><th>Time</th><th>Status</th>
      </tr>
    </thead>
    <tbody>
      {rows_joined}
    </tbody>
  </table>
</div>

<div class="footer">
  Generated by SCION Test Runner &nbsp;·&nbsp;
  {run_at} &nbsp;·&nbsp;
  {total} tests &nbsp;·&nbsp; {passed} passed &nbsp;·&nbsp; {failed} failed
</div>

</body>
</html>"""

    out_path.write_text(html, encoding="utf-8")
    return out_path


# ──────────────────────────────────────────────────────────────────────────────
# Rich display helpers
# ──────────────────────────────────────────────────────────────────────────────

def _print_lineage_chain(r: dict) -> None:
    ncs = r.get("node_checks", [])
    ecs = r.get("edge_checks", [])
    if not ncs:
        return
    parts = []
    for i, nc in enumerate(ncs):
        tick = f"{GREEN}✓{RESET}" if nc["found"] else f"{RED}✗{RESET}"
        parts.append(f"{tick} {nc['object']}")
        if i < len(ncs) - 1:
            edge_ok = ecs[i]["found"] if i < len(ecs) else True
            arrow = f"{GREEN}──✓──▶{RESET}" if edge_ok else f"{RED}──✗──▶{RESET}"
            parts.append(arrow)
    print("    " + " ".join(parts))


def _print_detail(r: dict) -> None:
    """Print a type-specific detail line after running a test."""
    tt = r.get("test_type", "")

    if tt == "lineage":
        _print_lineage_chain(r)

    elif tt == "impact":
        d = r.get("impact_detail", {})
        cnt   = d.get("direct_downstream_count", 0)
        names = d.get("direct_downstream", [])
        sample = [str(x).split(".")[-1] for x in names[:3]]
        print(f"    💥 Blast radius: {BOLD}{cnt}{RESET} downstream objects"
              + (f"  {DIM}(direct: {', '.join(sample)}){RESET}" if sample else ""))

    elif tt == "usage":
        d   = r.get("usage_detail", {})
        qc  = f"{d.get('query_count', 0):,}"
        uc  = d.get("user_count", 0)
        la  = d.get("last_accessed", "—")
        crit = d.get("criticality_level", "—")
        print(f"    📊 {BOLD}{qc}{RESET} queries  ·  "
              f"{BOLD}{uc}{RESET} users  ·  "
              f"last accessed: {la}  ·  "
              f"criticality: {BOLD}{crit}{RESET}")

    elif tt == "criticality":
        d = r.get("criticality_detail", {})
        lvl = d.get("criticality_level", "—")
        g   = d.get("graph_score", 0)
        u   = d.get("usage_score", 0)
        c   = d.get("combined_score", 0)
        print(f"    ⭐ Level: {BOLD}{lvl}{RESET}  |  "
              f"graph={g:.3f}  usage={u:.3f}  combined={c:.3f}")

    elif tt == "diff_count":
        d    = r.get("diff_count_detail", {})
        cnt  = d.get("changes_returned", 0)
        sfr  = d.get("snapshot_from", "?")
        sto  = d.get("snapshot_to", "?")
        typs = ", ".join(d.get("sample_types", [])[:5])
        print(f"    🔍 {BOLD}{cnt:,}{RESET} changes across snapshot "
              f"#{sfr} → #{sto}  |  types: {typs}")

    elif tt == "breaking":
        d    = r.get("breaking_detail", {})
        bc   = d.get("breaking_events", 0)
        typs = ", ".join(d.get("breaking_types", [])[:4])
        snps = d.get("breaking_snaps", [])
        print(f"    ⚡ {BOLD}{bc}{RESET} breaking change(s) detected: "
              f"{typs}  in snapshots {snps}")

    elif tt == "snapshot_health":
        checks = "  ·  ".join(r.get("health_checks", []))
        print(f"    🏥 {checks}  ·  all checks passed")

    elif tt == "landscape":
        d  = r.get("landscape_detail", {})
        hr = d.get("high_risk", 0)
        ec = d.get("entity_count", 0)
        rc = d.get("recent_changes", 0)
        print(f"    🗺  high_risk_count={BOLD}{hr}{RESET}  ·  "
              f"entity_count={BOLD}{ec:,}{RESET}  ·  "
              f"recent_changes={BOLD}{rc:,}{RESET}")

    elif tt == "reference":
        d    = r.get("reference_detail", {})
        res  = d.get("resource", "")
        cnt  = d.get("count", 0)
        samp = ", ".join(d.get("sample", [])[:3])
        print(f"    📋 {res}: {BOLD}{cnt}{RESET} records"
              + (f"  ·  sample: [{samp}]" if samp else ""))

    else:
        # changed / unchanged / added / dropped — show note if available
        note = r.get("note") or ""
        if note:
            print(f"    {DIM}{note}{RESET}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="SCION Test Runner")
    ap.add_argument("--base-url", default="http://localhost",
                    help="SCION base URL  (default: http://localhost)")
    ap.add_argument("--snapshot", type=int, default=None,
                    help="Snapshot ID for lineage / usage / impact tests (default: latest)")
    ap.add_argument("--snapshot-from", type=int, default=None,
                    help="Snapshot ID for diff 'from' side (default: snapshot just before --snapshot)")
    ap.add_argument("--hops", type=int, default=5,
                    help="BFS depth for lineage / impact traversal (default: 5)")
    ap.add_argument("--output", default=None,
                    help="Output path without extension (default: tests/results/<timestamp>)")
    ap.add_argument("--no-html", action="store_true", default=False,
                    help="Skip HTML report generation")
    args = ap.parse_args()

    # ── Banner ──
    banner = (
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║       SCION  ·  Automated Validation Suite                   ║\n"
        "║       Phase 1 + Phase 2  ·  PDCR  ·  Lineage  ·  Changes   ║\n"
        "╚══════════════════════════════════════════════════════════════╝"
    )
    print(f"{BOLD}{CYAN}{banner}{RESET}")
    print()

    test_files = sorted(TESTS_DIR.glob("Object_*.txt"))
    if not test_files:
        print(f"{RED}No test files found (expected tests/Object_*.txt).{RESET}")
        sys.exit(1)

    print(f"  {DIM}Base URL   :{RESET} {args.base_url}")
    print(f"  {DIM}Test files :{RESET} {len(test_files)}")

    try:
        snapshot_id        = args.snapshot or get_latest_snapshot(args.base_url)
        snap_from, snap_to = get_snapshot_pair(args.base_url, args.snapshot_from, snapshot_id)
    except Exception as e:
        print(f"\n{RED}{BOLD}ERROR:{RESET}{RED} Cannot reach SCION at {args.base_url}{RESET}\n  {e}")
        sys.exit(1)

    all_snaps  = get_snapshots(args.base_url)
    snap_count = len(all_snaps)

    print(f"  {DIM}Snapshot   :{RESET} #{snapshot_id}  {DIM}(lineage / usage / impact){RESET}")
    print(f"  {DIM}Diff pair  :{RESET} #{snap_from} → #{snap_to}  "
          f"{DIM}(changed / unchanged / added / dropped){RESET}")
    print(f"  {DIM}Snapshots  :{RESET} {snap_count} total")
    print()

    # ── Headline stats accumulators ──
    hl_objects      = None   # from snapshot_health
    hl_diff_count   = None   # (count, snap_from, snap_to) from diff_count
    hl_blast_obj    = None   # (object_name, count) — highest impact
    hl_max_usage    = None   # (query_count, object_name) — highest usage

    results      = []
    suite_start  = time.time()

    for tf in test_files:
        test      = parse_test_file(tf)
        test_type = test.get("test_type", "lineage")
        priority  = test.get("priority", "P3")
        obj_name  = test["object_name"]

        # Header line
        type_padded = f"[{test_type:<14}]"
        snap_override = test.get("snapshot_override")
        snap_tag = f" {CYAN}[snap #{snap_override}]{RESET}" if snap_override and snap_override != snapshot_id else ""
        obj_padded  = f"{obj_name:<40}"
        if test.get("skip"):
            print(f"  {DIM}► {type_padded} {obj_padded} ({priority}){RESET}")
        else:
            print(f"  {CYAN}►{RESET} {type_padded} {obj_padded}{snap_tag} {DIM}({priority}){RESET}")

        t0 = time.time()
        r  = run_test(args.base_url, snapshot_id, snap_from, snap_to, test, args.hops)
        elapsed_test = time.time() - t0
        r["elapsed"] = elapsed_test
        results.append(r)

        # Type-specific detail
        if r["status"] != "SKIP":
            _print_detail(r)

        # Accumulate headline stats
        if test_type == "snapshot_health" and r["status"] in ("PASS", "PARTIAL"):
            metrics = r.get("snapshot_metrics", {})
            for k in ("table_count", "object_count", "node_count", "total_objects"):
                v = metrics.get(k)
                if isinstance(v, int) and v > 0:
                    hl_objects = v
                    break

        if test_type == "diff_count" and r["status"] == "PASS":
            d   = r.get("diff_count_detail", {})
            cnt = d.get("changes_returned", 0)
            if hl_diff_count is None or cnt > hl_diff_count[0]:
                hl_diff_count = (cnt, d.get("snapshot_from"), d.get("snapshot_to"))

        if test_type == "impact" and r["status"] == "PASS":
            d   = r.get("impact_detail", {})
            cnt = d.get("direct_downstream_count", 0)
            if hl_blast_obj is None or cnt > hl_blast_obj[1]:
                hl_blast_obj = (obj_name, cnt)

        if test_type == "usage" and r["status"] == "PASS":
            d  = r.get("usage_detail", {})
            qc = d.get("query_count", 0)
            if hl_max_usage is None or qc > hl_max_usage[0]:
                hl_max_usage = (qc, obj_name)

        # Result line
        status = r["status"]
        if status == "PASS":
            icon = f"{GREEN}✓ PASS{RESET}"
        elif status == "FAIL":
            icon = f"{RED}✗ FAIL{RESET}"
        elif status == "PARTIAL":
            icon = f"{YELLOW}~ PARTIAL{RESET}"
        else:
            icon = f"{DIM}- SKIP{RESET}"

        time_str = f"{elapsed_test:.1f}s"
        if status == "FAIL":
            err_str = f": {r['error']}" if r.get("error") else ""
            print(f"      {icon}{RED}{err_str}{RESET}  {DIM}({time_str}){RESET}")
        elif status == "PARTIAL":
            err_str = f": {r['error']}" if r.get("error") else ""
            print(f"      {icon}{YELLOW}{err_str}{RESET}  {DIM}({time_str}){RESET}")
        else:
            print(f"      {icon}  {DIM}({time_str}){RESET}")

        print()  # blank line between tests

    total_elapsed = time.time() - suite_start

    # ── Progress separator ──
    print(f"  {DIM}{'━' * 62}{RESET}")
    print()

    # ── Count totals ──
    passed  = sum(1 for r in results if r["status"] == "PASS")
    partial = sum(1 for r in results if r["status"] == "PARTIAL")
    failed  = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")

    by_type: dict[str, dict] = {}
    for r in results:
        t = r.get("test_type", "lineage")
        by_type.setdefault(t, {"PASS": 0, "PARTIAL": 0, "FAIL": 0, "SKIP": 0})
        by_type[t][r["status"]] = by_type[t].get(r["status"], 0) + 1

    # ── Top summary line ──
    print(f"  {GREEN}{passed} PASS{RESET}  /  "
          f"{YELLOW}{partial} PARTIAL{RESET}  /  "
          f"{RED}{failed} FAIL{RESET}  /  "
          f"{DIM}{skipped} SKIP (pending setup){RESET}")
    print()

    # ── Summary table ──
    col_cat  = 21
    col_tot  = 7
    col_pass = 7
    col_part = 9
    col_fail = 6
    col_skip = 9

    def _row(cat, tot, p, pa, f, s, header=False):
        cc  = BOLD if header else ""
        pc  = f"{GREEN}{p}{RESET}" if (p and not header) else (str(p) if p else "")
        pac = f"{YELLOW}{pa}{RESET}" if (pa and not header) else (str(pa) if pa else "")
        fc  = f"{RED}{f}{RESET}" if (f and not header) else (str(f) if f else "")
        sc  = f"{DIM}{s}{RESET}" if (s and not header) else (str(s) if s else "")
        return (f"  │ {cc}{cat:<{col_cat}}{RESET}"
                f"│ {tot:>{col_tot-2}} "
                f"│ {pc:>{col_pass-2}} "
                f"│ {pac:>{col_part-2}} "
                f"│ {fc:>{col_fail-2}} "
                f"│ {sc:>{col_skip-2}} │")

    hr_top  = "  ┌" + "─"*col_cat + "┬" + "─"*col_tot + "┬" + "─"*col_pass + "┬" + "─"*col_part + "┬" + "─"*col_fail + "┬" + "─"*col_skip + "┐"
    hr_mid  = "  ├" + "─"*col_cat + "┼" + "─"*col_tot + "┼" + "─"*col_pass + "┼" + "─"*col_part + "┼" + "─"*col_fail + "┼" + "─"*col_skip + "┤"
    hr_bot  = "  └" + "─"*col_cat + "┴" + "─"*col_tot + "┴" + "─"*col_pass + "┴" + "─"*col_part + "┴" + "─"*col_fail + "┴" + "─"*col_skip + "┘"

    hdr = (f"  │ {'Test Category':<{col_cat}}"
           f"│ {'Total':>{col_tot-2}} "
           f"│ {GREEN}{'PASS':>{col_pass-2}}{RESET} "
           f"│ {YELLOW}{'PARTIAL':>{col_part-2}}{RESET} "
           f"│ {RED}{'FAIL':>{col_fail-2}}{RESET} "
           f"│ {DIM}{'SKIP':>{col_skip-2}}{RESET} │")

    print(hr_top)
    print(hdr)
    print(hr_mid)
    for ttype, counts in sorted(by_type.items()):
        p  = counts.get("PASS", 0)
        pa = counts.get("PARTIAL", 0)
        f  = counts.get("FAIL", 0)
        s  = counts.get("SKIP", 0)
        tot = p + pa + f + s
        print(_row(ttype, tot, p or "", pa or "", f or "", s or ""))
    print(hr_mid)
    print(_row("TOTAL", len(results), passed or "", partial or "", failed or "", skipped or "", header=True))
    print(hr_bot)
    print()

    # ── Headline stats box ──
    hl_lines = []
    if hl_objects is not None:
        hl_lines.append(
            f"  ║  Objects tracked:    {hl_objects:,}  across  {snap_count} snapshots           ║"
        )
    if hl_diff_count is not None:
        cnt, sf, st = hl_diff_count
        hl_lines.append(
            f"  ║  Changes detected:   {cnt:,}  (largest diff, snapshots {sf}→{st})   ║"
        )
    if hl_blast_obj is not None:
        obj, cnt = hl_blast_obj
        hl_lines.append(
            f"  ║  Highest blast radius: {obj}  ({cnt} nodes) ║"
        )
    if hl_max_usage is not None:
        qc, obj = hl_max_usage
        hl_lines.append(
            f"  ║  Max usage:          {qc:,} queries ({obj})        ║"
        )

    if hl_lines:
        box_top = "  ╔══════════════════════════════════════════════════════════════╗"
        box_ttl = "  ║  SCION PLATFORM HIGHLIGHTS                                   ║"
        box_sep = "  ║  ─────────────────────────────────────────────────────────  ║"
        box_bot = "  ╚══════════════════════════════════════════════════════════════╝"
        print(f"{BOLD}{CYAN}{box_top}{RESET}")
        print(f"{BOLD}{CYAN}{box_ttl}{RESET}")
        print(f"{BOLD}{CYAN}{box_sep}{RESET}")
        for line in hl_lines:
            print(f"{BOLD}{CYAN}{line}{RESET}")
        print(f"{BOLD}{CYAN}{box_bot}{RESET}")
        print()

    # ── Export JSON + CSV ──
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_base  = Path(args.output) if args.output else RESULTS_DIR / timestamp
    jp, cp    = export(results, out_base)
    print(f"  {DIM}Exported:{RESET}")
    print(f"    JSON : {jp}")
    print(f"    CSV  : {cp}")

    # ── Export HTML ──
    if not args.no_html:
        html_path = out_base.with_suffix(".html")
        export_html(results, html_path,
                    snapshot_id, snap_from, snap_to,
                    args.base_url, total_elapsed)
        print(f"    HTML : {html_path}")

    print()
    print(f"  Total time: {total_elapsed:.1f}s")
    print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
