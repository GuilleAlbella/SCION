import client from "./client";
import type { CoChangeResponse, VolatilityTrendResponse } from "./types";

export async function getScorecard(snapshotId: number): Promise<any> {
  const { data } = await client.get(`/intelligence/scorecard/${snapshotId}`);
  return data;
}

export async function getDomainRisk(snapshotId: number): Promise<any> {
  const { data } = await client.get(`/intelligence/domain-risk/${snapshotId}`);
  return data;
}

export async function getIntelligenceVolatility(): Promise<any> {
  const { data } = await client.get("/intelligence/volatility");
  return data;
}

export async function getStability(objectName: string): Promise<any> {
  const { data } = await client.get(`/intelligence/stability/${objectName}`);
  return data;
}

// ──── v1.07 Data-science pack ────

export async function getCoChange(
  minLift = 1.5,
  minPairSupport = 2,
  topN = 50,
): Promise<CoChangeResponse> {
  const { data } = await client.get<CoChangeResponse>("/intelligence/cochange", {
    params: { min_lift: minLift, min_pair_support: minPairSupport, top_n: topN },
  });
  return data;
}

export async function getVolatilityTrend(window = 3): Promise<VolatilityTrendResponse> {
  const { data } = await client.get<VolatilityTrendResponse>(
    "/intelligence/volatility-trend",
    { params: { window } },
  );
  return data;
}
