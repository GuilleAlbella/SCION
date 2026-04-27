from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import text

from app.db.engine import engine


def compute_downstream_impact(
    start_node_id: int,
    snapshot_id: int,
    max_depth: Optional[int] = None,
) -> List[Dict]:
    """Compute downstream impact starting from a given node.

    Traverses `graph_edge` following edges where `source_node_id` matches the
    current node, constrained to a single `snapshot_id`.

    The implementation uses a recursive CTE (WITH RECURSIVE) and builds a
    comma-separated path of node identifiers, which is then returned as a
    Python list of integers per result.
    """

    if start_node_id is None or snapshot_id is None:
        raise ValueError("start_node_id and snapshot_id must not be None")

    # We push the traversal into SQL (recursive CTE) rather than walking
    # the graph in Python because:
    #  1. It minimizes row-count shuttling between DB and app.
    #  2. SQLite/Postgres both handle WITH RECURSIVE efficiently.
    #  3. Cycle detection via a comma-delimited `path` string is portable
    #     (works on SQLite, which lacks arrays). The trick: wrap both the
    #     path and the candidate id in commas before calling instr() so
    #     `,12,` never matches inside `,120,`.
    recursive_sql = """
    WITH RECURSIVE impact(node_id, depth, path) AS (
        -- Seed: direct neighbours of the start node (depth 1 = "DIRECT")
        SELECT
            ge.target_node_id AS node_id,
            1 AS depth,
            printf('%d,%d', :start_node_id, ge.target_node_id) AS path
        FROM graph_edge ge
        WHERE ge.source_node_id = :start_node_id
          AND ge.snapshot_id = :snapshot_id

        UNION ALL

        -- Recursive step: follow edges outward one more hop
        SELECT
            ge.target_node_id AS node_id,
            impact.depth + 1 AS depth,
            impact.path || ',' || ge.target_node_id AS path
        FROM graph_edge ge
        JOIN impact ON ge.source_node_id = impact.node_id
        WHERE ge.snapshot_id = :snapshot_id
        -- Avoid cycles by preventing revisiting node_ids already in the path
          AND instr(',' || impact.path || ',', ',' || ge.target_node_id || ',') = 0
    )
    SELECT node_id, depth, path
    FROM impact
    WHERE (:max_depth IS NULL OR depth <= :max_depth)
    ORDER BY depth ASC, node_id ASC
    """

    with engine.connect() as conn:
        result = conn.execute(
            text(recursive_sql),
            {
                "start_node_id": start_node_id,
                "snapshot_id": snapshot_id,
                "max_depth": max_depth,
            },
        )
        rows = result.fetchall()

    impact_list: List[Dict] = []
    for row in rows:
        # Convert the comma-delimited path string back into a list of ints
        # so callers can consume it without knowing the SQL encoding detail.
        path_ids = [int(part) for part in str(row.path).split(",") if part]
        impact_list.append(
            {
                "node_id": row.node_id,
                "depth": row.depth,
                "relationship_path": path_ids,
                # Inverse-depth decay: directly impacted = 1.0, two hops
                # away = 0.5, three hops = 0.33… Rounded for stable output.
                "impact_score": round(1.0 / row.depth, 4),
            }
        )

    return impact_list


def compute_upstream_impact(
    start_node_id: int,
    snapshot_id: int,
    max_depth: Optional[int] = None,
) -> List[Dict]:
    """Compute upstream impact towards nodes that feed into the start node.

    Traverses `graph_edge` following edges where `target_node_id` matches the
    current node, constrained to a single `snapshot_id`.
    """

    if start_node_id is None or snapshot_id is None:
        raise ValueError("start_node_id and snapshot_id must not be None")

    # Mirror image of compute_downstream_impact: same CTE shape, but we
    # join on target_node_id = current node (walking backwards along edges)
    # to find producers rather than consumers.
    recursive_sql = """
    WITH RECURSIVE impact(node_id, depth, path) AS (
        -- Seed: direct predecessors of the start node
        SELECT
            ge.source_node_id AS node_id,
            1 AS depth,
            printf('%d,%d', ge.source_node_id, :start_node_id) AS path
        FROM graph_edge ge
        WHERE ge.target_node_id = :start_node_id
          AND ge.snapshot_id = :snapshot_id

        UNION ALL

        SELECT
            ge.source_node_id AS node_id,
            impact.depth + 1 AS depth,
            ge.source_node_id || ',' || impact.path AS path
        FROM graph_edge ge
        JOIN impact ON ge.target_node_id = impact.node_id
        WHERE ge.snapshot_id = :snapshot_id
        -- Avoid cycles by preventing revisiting node_ids already in the path
          AND instr(',' || impact.path || ',', ',' || ge.source_node_id || ',') = 0
    )
    SELECT node_id, depth, path
    FROM impact
    WHERE (:max_depth IS NULL OR depth <= :max_depth)
    ORDER BY depth ASC, node_id ASC
    """

    with engine.connect() as conn:
        result = conn.execute(
            text(recursive_sql),
            {
                "start_node_id": start_node_id,
                "snapshot_id": snapshot_id,
                "max_depth": max_depth,
            },
        )
        rows = result.fetchall()

    impact_list: List[Dict] = []
    for row in rows:
        path_ids = [int(part) for part in str(row.path).split(",") if part]
        impact_list.append(
            {
                "node_id": row.node_id,
                "depth": row.depth,
                "relationship_path": path_ids,
                "impact_score": round(1.0 / row.depth, 4),
            }
        )

    return impact_list
