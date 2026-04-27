import client from "./client";
import type { ImpactResponse, BatchImpactResponse } from "./types";

export async function runImpact(changeId: number): Promise<ImpactResponse> {
  const { data } = await client.post<ImpactResponse>(`/impact/${changeId}`);
  return data;
}

export async function runBatchImpact(
  snapshotFrom: number,
  snapshotTo: number
): Promise<BatchImpactResponse> {
  const { data } = await client.post<BatchImpactResponse>("/impact/batch", {
    snapshot_from: snapshotFrom,
    snapshot_to: snapshotTo,
  });
  return data;
}
