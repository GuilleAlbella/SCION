import client from "./client";
import type { TimelineResponse } from "./types";

export async function getTimeline(objectName: string): Promise<TimelineResponse> {
  const { data } = await client.get<TimelineResponse>("/timeline", {
    params: { object_name: objectName },
  });
  return data;
}

export async function getTimelineObjects(): Promise<{ objects: string[] }> {
  const { data } = await client.get<{ objects: string[] }>("/timeline/objects");
  return data;
}
