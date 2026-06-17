import client from "./client";
import type { ParserImportResponse } from "./types";

// Parser import client — posts a DataDNA parser JSON payload to the backend.
// The backend runs parse → noise_filter → (dry_run | ingest) and returns a
// flattened IngestionReport. We expose two thin wrappers so the UI can do a
// preview before it commits to persisting a snapshot.

export async function previewParserImport(
  payload: unknown
): Promise<ParserImportResponse> {
  const { data } = await client.post<ParserImportResponse>(
    "/parser-import/lineage?dry_run=true",
    payload
  );
  return data;
}

export async function confirmParserImport(
  payload: unknown,
  opts?: { sourceSystem?: string; description?: string; snapshotId?: number }
): Promise<ParserImportResponse> {
  const params = new URLSearchParams({ dry_run: "false" });
  if (opts?.sourceSystem) params.set("source_system", opts.sourceSystem);
  if (opts?.description) params.set("description", opts.description);
  if (opts?.snapshotId != null) params.set("snapshot_id", String(opts.snapshotId));
  const { data } = await client.post<ParserImportResponse>(
    `/parser-import/lineage?${params.toString()}`,
    payload
  );
  return data;
}
