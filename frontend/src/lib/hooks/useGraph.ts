import useSWR from "swr";
import { getGraph } from "@/lib/api/graph";
import type { GraphResponse } from "@/lib/api/types";

/**
 * useGraph — fetch the graph (nodes + edges) for a given snapshot.
 * Passing `null` as the key short-circuits SWR and skips the request,
 * which is the standard SWR pattern for conditional fetching when the
 * input isn't ready yet. The `!` on snapshotId is safe because the
 * fetcher only runs when the key is truthy.
 */
export function useGraph(snapshotId: number | null) {
  return useSWR<GraphResponse>(
    snapshotId != null ? `graph-${snapshotId}` : null,
    () => getGraph(snapshotId!),
  );
}
