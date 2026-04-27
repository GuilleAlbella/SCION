import client from "./client";
import type { AlertsResponse, AnomaliesResponse } from "./types";

export async function getAlerts(limit: number = 50): Promise<AlertsResponse> {
  const { data } = await client.get<AlertsResponse>("/alerts", {
    params: { limit },
  });
  return data;
}

// Statistical anomaly detector — separate endpoint because its payload has
// fields (z-score, expected vs observed, baseline size) that don't fit the
// generic AlertItem schema.
export async function getAnomalies(zThreshold = 2.0): Promise<AnomaliesResponse> {
  const { data } = await client.get<AnomaliesResponse>("/alerts/anomalies", {
    params: { z_threshold: zThreshold },
  });
  return data;
}
