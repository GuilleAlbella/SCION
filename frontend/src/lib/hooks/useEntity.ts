import useSWR from "swr";
import { getEntity, getEntityHistory } from "@/lib/api/entity";
import type { EntityResponse, EntityHistoryResponse } from "@/lib/api/types";

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
