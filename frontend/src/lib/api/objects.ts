import client from "./client";
import type { ObjectSearchParams, ObjectSearchResponse } from "./types";

/**
 * Search for object identifiers matching `q`. Backed by a single,
 * server-side autocomplete endpoint (`GET /objects/search`) that paginates
 * — at most `limit` items per call — and reports `has_more` so the UI
 * can render "Showing N of many — keep typing" affordances.
 *
 * Two backing sources are supported:
 *  - `source: "changes"` (default): distinct `object_identifier` values
 *    from the `change_event` table. Use this when the user is searching
 *    among objects that have actually changed.
 *  - `source: "graph"`: every node in the dependency graph for a given
 *    snapshot. Requires `snapshot_id`. Use this for picking simulation /
 *    what-if targets where any object — even ones that never changed —
 *    is a valid pick.
 */
export async function searchObjects(
  params: ObjectSearchParams = {},
): Promise<ObjectSearchResponse> {
  const { data } = await client.get<ObjectSearchResponse>("/objects/search", {
    params,
  });
  return data;
}
