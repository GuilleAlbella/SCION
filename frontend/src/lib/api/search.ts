import client from "./client";
import type { SearchResponse } from "./types";

export async function globalSearch(query: string): Promise<SearchResponse> {
  const { data } = await client.get<SearchResponse>("/search", {
    params: { q: query },
  });
  return data;
}
