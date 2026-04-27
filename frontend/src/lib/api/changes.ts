import client from "./client";
import type { ChangesResponse } from "./types";

export async function getChanges(): Promise<ChangesResponse> {
  const { data } = await client.get<ChangesResponse>("/changes");
  return data;
}
