import useSWR from "swr";
import { getSnapshots } from "@/lib/api/snapshots";
import type { SnapshotsResponse } from "@/lib/api/types";

/**
 * useSnapshots — fetch the list of all captured snapshots.
 * Default SWR config: cached by key ("snapshots"), revalidated on focus,
 * no polling (snapshots only change when the user explicitly captures).
 */
export function useSnapshots() {
  return useSWR<SnapshotsResponse>("snapshots", getSnapshots);
}
