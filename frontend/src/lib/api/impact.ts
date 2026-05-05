import client from "./client";
import type {
  BatchImpactRequestParams,
  BatchImpactResponse,
  ImpactResponse,
} from "./types";

export async function runImpact(changeId: number): Promise<ImpactResponse> {
  const { data } = await client.post<ImpactResponse>(`/impact/${changeId}`);
  return data;
}

/**
 * Run paginated batch impact analysis on a snapshot pair.
 *
 * The response is paginated server-side via `params.limit` / `params.offset`,
 * but `summary` and `blast_radius` are always computed over the FULL filtered
 * set — so the Impact Analysis page can render KPIs and donuts off them
 * without iterating the (paginated) `changes` list. See `BatchImpactResponse`.
 */
export async function runBatchImpact(
  snapshotFrom: number,
  snapshotTo: number,
  params: BatchImpactRequestParams = {},
): Promise<BatchImpactResponse> {
  const { data } = await client.post<BatchImpactResponse>("/impact/batch", {
    snapshot_from: snapshotFrom,
    snapshot_to: snapshotTo,
    ...params,
  });
  return data;
}
