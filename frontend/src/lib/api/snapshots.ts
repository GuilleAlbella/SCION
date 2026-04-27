import client from "./client";
import type { SnapshotsResponse } from "./types";

export async function getSnapshots(): Promise<SnapshotsResponse> {
  const { data } = await client.get<SnapshotsResponse>("/snapshots");
  return data;
}

export async function createSnapshot(): Promise<{ snapshot_id: string }> {
  const { data } = await client.post<{ snapshot_id: string }>("/snapshots");
  return data;
}

export interface DeleteSnapshotResponse {
  deleted_snapshot_id: number;
  cascade: Record<string, number>;
  message: string;
}

export async function deleteSnapshot(snapshotId: number): Promise<DeleteSnapshotResponse> {
  const { data } = await client.delete<DeleteSnapshotResponse>(
    `/snapshots/${snapshotId}?confirm_id=${snapshotId}`
  );
  return data;
}
