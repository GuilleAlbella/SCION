import client from "./client";
import type { DiffRequest, DiffResponse, DiffDetailResponse } from "./types";

export async function runDiff(req: DiffRequest): Promise<DiffResponse> {
  const { data } = await client.post<DiffResponse>("/diff", req);
  return data;
}

export async function getDiffDetails(
  snapshotFrom: number,
  snapshotTo: number
): Promise<DiffDetailResponse> {
  const { data } = await client.get<DiffDetailResponse>(
    `/diff/${snapshotFrom}/${snapshotTo}/details`
  );
  return data;
}
