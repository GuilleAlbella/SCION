import client from "./client";
import type { SimulationRequest, SimulationResponse } from "./types";

export async function runSimulation(req: SimulationRequest): Promise<SimulationResponse> {
  const { data } = await client.post<SimulationResponse>("/simulation", req);
  return data;
}
