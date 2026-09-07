import client from "./client";
import type {
  DiffRequest,
  DiffResponse,
  DiffDetailResponse,
  DiffDetailsParams,
} from "./types";

export async function runDiff(req: DiffRequest): Promise<DiffResponse> {
  const { data } = await client.post<DiffResponse>("/diff", req, { timeout: 0 });
  return data;
}

/**
 * Fetch one page of change events between two snapshots.
 *
 * The endpoint is paginated; `params.limit` and `params.offset` control the
 * page boundary, and the optional `severity` / `is_breaking` / `object_q`
 * filters are applied server-side (so the summary KPIs reflect the full
 * filtered set, not just the page).
 *
 * Defaults match the server (`limit=100`, `offset=0`, no filters), which
 * is what the legacy single-call call sites need to keep working without
 * passing params.
 */
export async function getDiffDetails(
  snapshotFrom: number,
  snapshotTo: number,
  params: DiffDetailsParams = {},
): Promise<DiffDetailResponse> {
  const { data } = await client.get<DiffDetailResponse>(
    `/diff/${snapshotFrom}/${snapshotTo}/details`,
    { params },
  );
  return data;
}
