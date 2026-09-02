import useSWR from "swr";
import { getEntity, getEntityHistory, getEntityContext, resolveEntity } from "@/lib/api/entity";
import type { EntityResponse, EntityHistoryResponse, EntityContextResponse } from "@/lib/api/types";

export function useEntity(entityId: number | null) {
  return useSWR<EntityResponse>(
    entityId != null ? `entity-${entityId}` : null,
    () => getEntity(entityId!),
  );
}

export function useEntityHistory(entityId: number | null) {
  return useSWR<EntityHistoryResponse>(
    entityId != null ? `entity-history-${entityId}` : null,
    () => getEntityHistory(entityId!),
  );
}

export function useEntityContext(entityId: number | null) {
  return useSWR<EntityContextResponse>(
    entityId != null ? `entity-context-${entityId}` : null,
    () => getEntityContext(entityId!),
  );
}

export function useEntityResolve(name: string | null, type = "TABLE") {
  return useSWR<EntityResponse>(
    name ? `entity-resolve-${type}-${name}` : null,
    () => resolveEntity(name!, type),
    { shouldRetryOnError: false },
  );
}
