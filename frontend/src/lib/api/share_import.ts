import apiClient from "@/lib/api/client";
import type { DictImportResponse } from "@/lib/api/dict_import";

export interface ShareScanResponse {
  share_available: boolean;
  share_path: string;
  dict_files: string[];
  pdcr_files: string[];
  lineage_files: string[];
}

export interface ShareImportResponse {
  snapshot_id: number;
  dict_result: DictImportResponse;
  lineage_attached: boolean;
  lineage_tables: number;
  lineage_edges: number;
  lineage_columns: number;
  lineage_warnings: string[];
}

export async function scanShare(path?: string): Promise<ShareScanResponse> {
  const params = path ? `?path=${encodeURIComponent(path)}` : "";
  const { data } = await apiClient.get<ShareScanResponse>(`/share-import/scan${params}`);
  return data;
}

export async function importFromShare(force = false, path?: string): Promise<ShareImportResponse> {
  const params = new URLSearchParams({ force: String(force) });
  if (path) params.set("path", path);
  const { data } = await apiClient.post<ShareImportResponse>(`/share-import?${params}`);
  return data;
}
