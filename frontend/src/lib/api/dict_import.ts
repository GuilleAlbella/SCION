// Dict-import client — uploads up to 6 data-dictionary files (any
// combination of databases / tables / columns / indices / partitioning /
// tabletext) to the backend's POST /api/v1/dict-import endpoint and
// returns a typed response with per-category counts.
//
// The endpoint is multipart/form-data — we deviate from the JSON-only
// pattern used by the rest of the API client because the dict pipeline
// accepts raw `.dat` files. Axios handles the boundary header itself
// when we hand it a FormData instance.
//
// Progress tracking: the import takes 5-10 minutes for production-scale
// extracts. The browser can't show in-band progress while waiting on
// the long POST, so we use a parallel polling channel: the client
// generates an `import_id` (UUID) and sends it as a form field; the
// backend writes per-step state to an in-memory dict keyed by that id;
// a separate `GET /{import_id}/progress` endpoint returns the latest
// state. `pollImportProgress` below opens that channel.

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
  // PDCR fields (Pipeline 3) — present when PDCR files were included
  dbql_inserted?: number;
  object_usage_inserted?: number;
  object_usage_skipped_orphan?: number;
  criticality_recomputed?: boolean;
  criticality_high_count?: number;
  criticality_medium_count?: number;
  criticality_low_count?: number;
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

// ──── Server-side per-step progress (matches `import_progress.py`) ────

export type ImportStepStatus = "pending" | "running" | "done" | "error";

export interface ImportStep {
  /** Stable machine identifier (e.g. "upload", "persist_data"). */
  name: string;
  /** User-facing label rendered in the checklist. */
  label: string;
  status: ImportStepStatus;
  /** 0..1 fractional progress, or null for indeterminate. */
  progress: number | null;
  /** Free-form text shown next to the bar (row counts, etc). */
  caption: string | null;
  /** Wall-clock seconds since this step started, null if not started. */
  elapsed_seconds: number | null;
}

export interface ImportProgressState {
  import_id: string;
  status: "running" | "done" | "error" | "cancelled";
  error_message: string | null;
  total_elapsed_seconds: number;
  /** Server-side flag set by `/cancel`. The client doesn't need to
   *  read this directly (it watches `status === "cancelled"`), but
   *  it's exposed for diagnostics. */
  cancel_requested?: boolean;
  steps: ImportStep[];
}

/**
 * Request cooperative cancellation of an in-flight import.
 *
 * Fires a `POST /{import_id}/cancel` which sets a flag on the server-
 * side state. The handler polls that flag at known checkpoints
 * (every ~250k rows during the column persist) and rolls back when
 * it sees it set. The actual stop usually lands within ~6 seconds
 * of the click — fast enough for the UX, slow enough that the
 * cancel doesn't have to wedge itself into every hot-loop iteration.
 *
 * 404 means there's nothing to cancel (import already finished or
 * never registered) — we swallow it and return `false` because from
 * the user's perspective "nothing to cancel" is the same outcome
 * as "successfully cancelled".
 */
export async function cancelImport(importId: string): Promise<boolean> {
  // Retry on 404 because there's a small window after the user clicks
  // Upload where the server hasn't yet entered the handler (FastAPI
  // doesn't dispatch a multipart POST until the body is fully read,
  // which takes a couple of seconds for a 2.4 GB upload). Without the
  // retry, an impatient click while the body is still streaming would
  // 404 and the user would have to click Cancel again.
  //
  // 6 attempts * 500 ms = 3 s window. Covers the typical
  // localhost upload phase; longer-running uploads (slow disks /
  // network) will have already triggered other UI feedback by then.
  const maxAttempts = 6;
  const retryDelayMs = 500;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      await client.post(`/dict-import/${importId}/cancel`, undefined, {
        timeout: 5_000,
      });
      // eslint-disable-next-line no-console
      console.info(
        `[dict-import] cancel POST acknowledged for ${importId} (attempt ${attempt + 1})`,
      );
      return true;
    } catch (e) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const status = (e as any)?.response?.status;
      if (status === 404 && attempt < maxAttempts - 1) {
        // Backend hasn't registered the import yet — wait briefly
        // and retry. Don't log on these because they're expected
        // during the upload window; logging would just be noise.
        await new Promise((r) => setTimeout(r, retryDelayMs));
        continue;
      }
      if (status === 404) return false; // exhausted retries
      // eslint-disable-next-line no-console
      console.error(`[dict-import] cancel POST failed:`, e);
      throw e;
    }
  }
  return false;
}

/** Generate an import_id that the client can use to correlate the POST
 *  with the polling channel. Uses `crypto.randomUUID()` where available;
 *  falls back to a Math.random-based UUID for older browsers (we only
 *  need uniqueness within a session, not crypto-quality randomness). */
export function makeImportId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  // Fallback. RFC4122 v4 layout, just not crypto-strong.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
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
 *                         "server processing" mode.
 * @param importId         Optional client-generated UUID. When supplied,
 *                         the backend registers per-step progress against
 *                         it which the caller can read via
 *                         `pollImportProgress(importId)` in parallel.
 */
export async function importDictBatch(
  files: File[],
  force = false,
  onUploadProgress?: (e: UploadProgressEvent) => void,
  importId?: string,
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
  if (importId) {
    fd.append("import_id", importId);
  }

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

/**
 * Open a polling channel that mirrors the backend's per-step progress
 * for `importId`. Calls `onUpdate` every time a fresh snapshot is
 * fetched. Stops automatically when the server reports a terminal
 * status (`done` / `error` / `cancelled`) or when `signal` is aborted.
 *
 * Implementation notes:
 *
 *   - **Per-request timeout (10 s)**. Without this an in-flight poll
 *     could hang forever if the backend is busy on the persist hot
 *     path — and `setTimeout(tick, ...)` only fires after the
 *     `await` resolves, so a single hung request kills the whole
 *     channel. With the timeout, axios cancels the stuck request
 *     and the catch path schedules the next tick.
 *
 *   - **Always reschedule.** Every code path that doesn't terminate
 *     the channel must call `setTimeout(tick, intervalMs)` so a
 *     transient error never silently breaks the stream.
 *
 *   - **Diagnostic logging.** Errors that aren't 404 (which is the
 *     legitimate "POST hasn't reached init() yet" race) are logged
 *     to the dev console so we can debug stuck polls without having
 *     to re-instrument from scratch.
 */
export function pollImportProgress(
  importId: string,
  onUpdate: (state: ImportProgressState) => void,
  signal: AbortSignal,
): void {
  const intervalMs = 1000;
  const requestTimeoutMs = 10_000;

  const tick = async () => {
    if (signal.aborted) return;
    try {
      const { data } = await client.get<ImportProgressState>(
        `/dict-import/${importId}/progress`,
        { timeout: requestTimeoutMs },
      );
      if (signal.aborted) return;
      onUpdate(data);
      if (
        data.status === "done" ||
        data.status === "error" ||
        data.status === "cancelled"
      ) {
        return;
      }
    } catch (err) {
      // 404 before the backend has registered the import is benign
      // (race between this poll and the POST reaching `init()`).
      // Anything else (timeout, 5xx, network blip) we log so we
      // stop guessing why polling looks stuck in production runs.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const status = (err as any)?.response?.status;
      if (status !== 404) {
        // eslint-disable-next-line no-console
        console.warn(
          `[dict-import] progress poll error (will retry):`,
          err,
        );
      }
    }
    if (!signal.aborted) {
      setTimeout(tick, intervalMs);
    }
  };

  // Kick off the first poll immediately (no initial delay) so the UI
  // shows the checklist within ~50 ms of the user clicking Upload.
  void tick();
}
