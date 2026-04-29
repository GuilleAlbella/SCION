import client from "./client";
import type { CriticalityResponse } from "./types";

/**
 * Top objects by query count.
 *
 * If `snapshotId` is provided, the result is restricted to objects
 * that exist in that snapshot's graph (intersected against
 * UsageEvent.object_name). Without it, returns the global aggregation
 * across every recorded usage event — which is misleading on multi-
 * source DBs and is kept only for a legacy caller; new code should
 * always pass the snapshot.
 */
export async function getUsageSummary(
  snapshotId?: number
): Promise<{ items: any[]; total: number; snapshot_id?: number | null }> {
  const url = snapshotId != null
    ? `/usage/summary?snapshot_id=${snapshotId}`
    : "/usage/summary";
  const { data } = await client.get(url);
  return data;
}

export async function getCriticality(
  snapshotId: number
): Promise<CriticalityResponse> {
  const { data } = await client.get<CriticalityResponse>(
    `/usage/criticality/${snapshotId}`
  );
  return data;
}
