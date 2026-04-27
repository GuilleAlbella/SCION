import client from "./client";
import type { EngineControlResponse } from "./types";

export async function stopEngine(
  name: string
): Promise<EngineControlResponse> {
  const { data } = await client.post<EngineControlResponse>(
    `/control/stop/${name}`
  );
  return data;
}

export async function restartEngine(
  name: string
): Promise<EngineControlResponse> {
  const { data } = await client.post<EngineControlResponse>(
    `/control/restart/${name}`
  );
  return data;
}
