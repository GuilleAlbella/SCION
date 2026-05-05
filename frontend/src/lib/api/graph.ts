import client from "./client";
import type { FocusedGraphParams, FocusedGraphResponse, GraphResponse } from "./types";

export async function getGraph(snapshotId: number): Promise<GraphResponse> {
  const { data } = await client.get<GraphResponse>(`/graph/${snapshotId}`);
  return data;
}

/**
 * Server-side BFS around an anchor object — bounded subgraph for
 * visualisation pages. The backend caps `max_nodes` at 1000 regardless
 * of what we send; UI defaults of 200 are usually sufficient for a
 * useful local neighbourhood.
 *
 * Used by `/lineage` on every fetch (it never needs the full graph)
 * and by `/graph` when the full graph exceeds the truncation cap and
 * the user picks an anchor to focus on.
 */
export async function getFocusedGraph(
  params: FocusedGraphParams,
): Promise<FocusedGraphResponse> {
  const { data } = await client.get<FocusedGraphResponse>(
    "/graph/focus",
    { params },
  );
  return data;
}
