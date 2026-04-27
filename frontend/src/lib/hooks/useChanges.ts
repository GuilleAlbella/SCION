import useSWR from "swr";
import { getChanges } from "@/lib/api/changes";
import type { ChangesResponse } from "@/lib/api/types";

/**
 * useChanges — fetch the full change event list. Thin SWR wrapper kept
 * alongside the other hooks for consistency; pages import this instead
 * of calling the API module directly so we get caching, dedupe, and
 * focus-revalidation for free.
 */
export function useChanges() {
  return useSWR<ChangesResponse>("changes", getChanges);
}
