// Dict-import client — uploads up to 6 data-dictionary files (any
// combination of databases / tables / columns / indices / partitioning /
// tabletext) to the backend's POST /api/v1/dict-import endpoint and
// returns a typed response with per-category counts.
//
// The endpoint is multipart/form-data — we deviate from the JSON-only
// pattern used by the rest of the API client because the dict pipeline
// accepts raw `.dat` files. Axios handles the boundary header itself
// when we hand it a FormData instance.

import client from "./client";

export interface DictImportResponse {
  snapshot_id: number;
  skipped_existing: boolean;
  source_system_name: string;
  extract_run_id: string;
  schemas_created: number;
  tables_created: number;
  columns_created: number;
  indices_seen: number;
  partitioning_seen: number;
  tabletext_seen: number;
  files_received: number;
}

/**
 * Upload one batch of dict files. Caller must pass at least one file;
 * any combination of the 6 views is accepted in any order — the
 * endpoint detects each file's content type from bytes + filename.
 *
 * @param files       1–6 File objects from a drag-drop or `<input>`.
 * @param force       If true, ignore existing snapshot with same
 *                    `extract_run_id` and create a duplicate (testing only).
 */
export async function importDictBatch(
  files: File[],
  force = false,
): Promise<DictImportResponse> {
  if (files.length === 0) {
    throw new Error("No files selected for dict import.");
  }

  // FormData carries the files plus the `force` flag. Axios infers
  // the multipart Content-Type header automatically when we hand it
  // a FormData; we explicitly clear the JSON Content-Type from the
  // shared client so it doesn't override the boundary header.
  const fd = new FormData();
  for (const f of files) {
    fd.append("files", f, f.name);
  }
  fd.append("force", String(force));

  const { data } = await client.post<DictImportResponse>(
    "/dict-import",
    fd,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}
