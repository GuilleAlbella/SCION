import client from "./client";
import type { TimelineResponse, TimelineParams } from "./types";

export async function getTimeline(
  objectName: string,
  params: TimelineParams = {},
): Promise<TimelineResponse> {
  const { data } = await client.get<TimelineResponse>("/timeline", {
    params: { object_name: objectName, ...params },
  });
  return data;
}

/** @deprecated Use `searchObjects()` from `./objects` instead. The legacy
 *  endpoint loads up to 1000 distinct identifiers in a single shot, which
 *  isn't usable on production-scale extracts. Kept here for any caller
 *  that hasn't migrated yet; will be removed once nothing references it. */
export async function getTimelineObjects(): Promise<{ objects: string[] }> {
  const { data } = await client.get<{ objects: string[] }>("/timeline/objects");
  return data;
}
