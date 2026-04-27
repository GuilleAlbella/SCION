import client from "./client";
import type {
  SnapshotMetricsResponse,
  GrowthResponse,
  VolatilityResponse,
} from "./types";

export async function getSnapshotMetrics(
  snapshotId: number
): Promise<SnapshotMetricsResponse> {
  const { data } = await client.get<SnapshotMetricsResponse>(
    `/metrics/snapshot/${snapshotId}`
  );
  return data;
}

export async function getGrowthRate(
  from: number,
  to: number
): Promise<GrowthResponse> {
  const { data } = await client.get<GrowthResponse>("/metrics/growth", {
    params: { from, to },
  });
  return data;
}

export async function getVolatility(): Promise<VolatilityResponse> {
  const { data } = await client.get<VolatilityResponse>("/metrics/volatility");
  return data;
}
