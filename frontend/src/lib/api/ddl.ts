import client from "./client";
import type { DDLResponse } from "./types";

export async function getDDL(
  snapshotFrom: number,
  snapshotTo: number
): Promise<DDLResponse> {
  const { data } = await client.get<DDLResponse>(
    `/ddl/${snapshotFrom}/${snapshotTo}`
  );
  return data;
}
