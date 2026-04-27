import client from "./client";
import type { CriticalityResponse } from "./types";

export async function getUsageSummary(): Promise<{ items: any[]; total: number }> {
  const { data } = await client.get("/usage/summary");
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
