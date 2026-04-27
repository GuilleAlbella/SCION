import useSWR from "swr";
import { getHealth } from "@/lib/api/health";
import type { HealthResponse } from "@/lib/api/types";

/**
 * useHealth — polls the backend /health endpoint every 5 seconds so the
 * sidebar status indicator reflects live state (mock/real/degraded).
 * SWR dedupes the "health" key across components, so multiple callers
 * share a single in-flight poll.
 */
export function useHealth() {
  return useSWR<HealthResponse>("health", getHealth, {
    refreshInterval: 5000,
  });
}
