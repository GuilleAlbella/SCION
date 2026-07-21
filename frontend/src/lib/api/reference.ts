import client from "./client";
import type {
  AppImportResponse,
  AppUsageResponse,
  ApplicationsResponse,
  ReferenceStatus,
  TeamUsageResponse,
  TeamsResponse,
  UserImportResponse,
} from "./types";

export async function getReferenceStatus(): Promise<ReferenceStatus> {
  const { data } = await client.get("/reference-import/status");
  return data;
}

export async function uploadUsers(file: File): Promise<UserImportResponse> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post("/reference-import/users", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function uploadApplications(file: File): Promise<AppImportResponse> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post("/reference-import/applications", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function getTeams(): Promise<TeamsResponse> {
  const { data } = await client.get("/reference/teams");
  return data;
}

export async function getApplications(): Promise<ApplicationsResponse> {
  const { data } = await client.get("/reference/applications");
  return data;
}

export async function getUsageByTeam(snapshotId?: number): Promise<TeamUsageResponse> {
  const { data } = await client.get("/reference/usage-by-team", {
    params: snapshotId ? { snapshot_id: snapshotId } : {},
  });
  return data;
}

export async function getUsageByApp(snapshotId?: number): Promise<AppUsageResponse> {
  const { data } = await client.get("/reference/usage-by-app", {
    params: snapshotId ? { snapshot_id: snapshotId } : {},
  });
  return data;
}
