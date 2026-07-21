import client from "./client";
import type { ClassifyColumnsResponse, ColumnLineageResponse, ColumnTraverseResponse, FocusedGraphParams, FocusedGraphResponse, GraphResponse, PiiResponse } from "./types";

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
export async function getColumnLineage(
  snapshotId: number,
  object: string,
  tier?: string,
): Promise<ColumnLineageResponse> {
  const params: Record<string, string | number> = { snapshot_id: snapshotId, object };
  if (tier) params.tier = tier;
  const { data } = await client.get<ColumnLineageResponse>("/lineage/columns", { params });
  return data;
}

export async function traverseColumnLineage(
  snapshotId: number,
  columnKey: string,
  direction: "downstream" | "upstream" = "downstream",
  maxDepth: number = 10,
): Promise<ColumnTraverseResponse> {
  const { data } = await client.get<ColumnTraverseResponse>("/lineage/columns/traverse", {
    params: { snapshot_id: snapshotId, column_key: columnKey, direction, max_depth: maxDepth },
  });
  return data;
}

export async function getColumnPii(
  snapshotId: number,
  object: string,
): Promise<PiiResponse> {
  const { data } = await client.get<PiiResponse>("/columns/pii", {
    params: { snapshot_id: snapshotId, object },
  });
  return data;
}

export async function classifyColumns(
  snapshotId: number,
  object?: string,
  force = false,
  limit = 500,
): Promise<ClassifyColumnsResponse> {
  const { data } = await client.post<ClassifyColumnsResponse>("/columns/classify", null, {
    params: { snapshot_id: snapshotId, object, force, limit },
  });
  return data;
}

export async function getFocusedGraph(
  params: FocusedGraphParams,
): Promise<FocusedGraphResponse> {
  const { data } = await client.get<FocusedGraphResponse>(
    "/graph/focus",
    { params },
  );
  return data;
}
