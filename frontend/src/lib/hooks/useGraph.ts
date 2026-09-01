import useSWR from "swr";
import { getGraph, getGraphMeta } from "@/lib/api/graph";
import type { GraphMetaResponse, GraphResponse } from "@/lib/api/types";

/**
 * useGraph — fetch the full graph (nodes + edges) for a snapshot.
 *
 * §2.7 adds an `enabled` option. When false (or when snapshotId is null)
 * SWR is short-circuited and no request is made. The graph page uses this
 * for lazy loading: it first fetches the cheap `/meta` probe and only sets
 * enabled=true after the user explicitly triggers the load (or the node
 * count is below LAZY_GRAPH_THRESHOLD).
 */
export function useGraph(
  snapshotId: number | null,
  opts: { enabled?: boolean } = {},
) {
  const { enabled = true } = opts;
  return useSWR<GraphResponse>(
    snapshotId != null && enabled ? `graph-${snapshotId}` : null,
    () => getGraph(snapshotId!),
  );
}

/**
 * useGraphMeta — lightweight COUNT-only probe (GET /graph/{id}/meta).
 *
 * §2.7 Lazy graph fetch: always auto-fetches because it's sub-millisecond
 * (two COUNT(*) queries on indexed columns). The graph page uses
 * `total_nodes` to decide whether to auto-load the full graph or show a
 * "Load Graph (N nodes)" button.
 */
export function useGraphMeta(snapshotId: number | null) {
  return useSWR<GraphMetaResponse>(
    snapshotId != null ? `graph-meta-${snapshotId}` : null,
    () => getGraphMeta(snapshotId!),
  );
}
