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
  snapshotId: number,
  objectQ?: string
): Promise<CriticalityResponse> {
  const qs = objectQ ? `?object_q=${encodeURIComponent(objectQ)}` : "";
  const { data } = await client.get<CriticalityResponse>(
    `/usage/criticality/${snapshotId}${qs}`
  );
  return data;
}

/** Full usage + criticality profile for a single object — backs the
 *  Usage page's per-object drill-down. Resolves any object, even one
 *  outside the top-N summary / criticality rankings. */
export interface ObjectUsageDetail {
  snapshot_id: number;
  object: string;
  found: boolean;
  object_type: string | null;
  schema_name: string | null;
  usage: {
    query_count: number;
    user_count: number;
    last_accessed: string | null;
    has_data: boolean;
  };
  criticality: {
    usage_score: number;
    graph_score: number;
    combined_score: number;
    criticality_level: string;
  } | null;
}

export async function getObjectUsageDetail(
  snapshotId: number,
  object: string
): Promise<ObjectUsageDetail> {
  const { data } = await client.get<ObjectUsageDetail>(
    `/usage/object/${snapshotId}?object=${encodeURIComponent(object)}`
  );
  return data;
}
