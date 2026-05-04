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
  indices_created: number;
  partitioning_created: number;
  ddl_text_created: number;
  indices_seen: number;
  partitioning_seen: number;
  tabletext_seen: number;
  files_received: number;
}

/** Upload-progress callback shape, mirrored from axios's `progressEvent`
 * but typed independently so callers don't need to depend on axios. */
export interface UploadProgressEvent {
  /** Bytes uploaded so far. */
  loaded: number;
  /** Total bytes to upload. May be undefined for very small payloads
   *  where the browser doesn't expose it; treat as unknown then. */
  total?: number;
  /** True once the browser reports the request body fully sent.
   *  After this the client is waiting for the server to finish
   *  processing; UI should switch to the "processing" phase. */
  uploadComplete: boolean;
}

/**
 * Upload one batch of dict files. Caller must pass at least one file;
 * any combination of the 6 views is accepted in any order — the
 * endpoint detects each file's content type from bytes + filename.
 *
 * @param files            1–6 File objects from a drag-drop or `<input>`.
 * @param force            If true, ignore existing snapshot with same
 *                         `extract_run_id` and create a duplicate (testing only).
 * @param onUploadProgress Optional callback fired as bytes go up the wire.
 *                         Called with `uploadComplete=true` exactly once,
 *                         the moment the body is fully sent — at which
 *                         point the UI should switch from "uploading" to
 *                         "server processing" mode (server-side parsing
 *                         + persisting can take several minutes for
 *                         multi-GB extracts).
 */
export async function importDictBatch(
  files: File[],
  force = false,
  onUploadProgress?: (e: UploadProgressEvent) => void,
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
    {
      headers: { "Content-Type": "multipart/form-data" },
      // Axios calls this on every chunk uploaded. We forward only the
      // fields the UI needs and append a synthetic `uploadComplete`
      // flag — by the time `loaded === total` we know the body is on
      // the server's socket and the request is now blocked on the
      // server doing its parse + persist work.
      onUploadProgress: onUploadProgress
        ? (e) => {
            const total = typeof e.total === "number" ? e.total : undefined;
            const uploadComplete = total !== undefined && e.loaded >= total;
            onUploadProgress({ loaded: e.loaded, total, uploadComplete });
          }
        : undefined,
      // Default 0 = unlimited. Multi-GB uploads can take many minutes
      // and we don't want axios to abort partway through — the user
      // can always cancel via the X button.
      timeout: 0,
      // Lift the multipart body size cap. Without these, axios's
      // default 10 MB limit aborts the upload silently around the
      // first columnsv chunk on a real customer extract.
      maxBodyLength: Infinity,
      maxContentLength: Infinity,
    },
  );
  return data;
}
