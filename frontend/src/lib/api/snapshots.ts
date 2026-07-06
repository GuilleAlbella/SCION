import client from "./client";
import type { SnapshotsResponse, SnapshotDetail } from "./types";

export async function getSnapshots(): Promise<SnapshotsResponse> {
  const { data } = await client.get<SnapshotsResponse>("/snapshots");
  return data;
}

export async function createSnapshot(): Promise<{ snapshot_id: string }> {
  const { data } = await client.post<{ snapshot_id: string }>("/snapshots");
  return data;
}

/** Outcome of the post-delete VACUUM that physically reclaims free
 *  space in the SQLite file. SQLite default settings only mark
 *  deleted pages as free without shrinking the file; VACUUM rebuilds
 *  it. All fields are nullable because the operation is best-effort:
 *  a failed VACUUM is logged but doesn't fail the whole delete. */
export interface SnapshotVacuumInfo {
  bytes_before: number | null;
  bytes_after: number | null;
  bytes_freed: number | null;
  elapsed_seconds: number | null;
  skipped_reason: string | null;
}

export interface DeleteSnapshotResponse {
  deleted_snapshot_id: number;
  cascade: Record<string, number>;
  vacuum: SnapshotVacuumInfo;
  message: string;
}

export async function getSnapshotDetail(snapshotId: number): Promise<SnapshotDetail> {
  const { data } = await client.get<SnapshotDetail>(`/snapshots/${snapshotId}/detail`);
  return data;
}

export async function deleteSnapshot(snapshotId: number): Promise<DeleteSnapshotResponse> {
  const { data } = await client.delete<DeleteSnapshotResponse>(
    `/snapshots/${snapshotId}?confirm_id=${snapshotId}`
  );
  return data;
}
