import client from "./client";
import type { GraphResponse } from "./types";

export async function getGraph(snapshotId: number): Promise<GraphResponse> {
  const { data } = await client.get<GraphResponse>(`/graph/${snapshotId}`);
  return data;
}
