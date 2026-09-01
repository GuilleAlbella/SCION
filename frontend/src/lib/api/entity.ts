import client from "./client";
import type {
  EntityResponse,
  EntityHistoryResponse,
  EntityListResponse,
} from "./types";

export async function getEntity(entityId: number): Promise<EntityResponse> {
  const { data } = await client.get<EntityResponse>(`/entity/${entityId}`);
  return data;
}

export async function getEntityHistory(
  entityId: number
): Promise<EntityHistoryResponse> {
  const { data } = await client.get<EntityHistoryResponse>(
    `/entity/${entityId}/history`
  );
  return data;
}

export async function resolveEntity(
  name: string,
  type = "TABLE"
): Promise<EntityResponse> {
  const { data } = await client.get<EntityResponse>("/entity/resolve", {
    params: { name, type },
  });
  return data;
}

export async function listEntities(params?: {
  schema?: string;
  type?: string;
  active_only?: boolean;
  limit?: number;
  offset?: number;
}): Promise<EntityListResponse> {
  const { data } = await client.get<EntityListResponse>("/entity/", {
    params,
  });
  return data;
}
