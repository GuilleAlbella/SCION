// Client-side row-count estimation for dict-import files.
//
// We could parse and count every line in the browser before upload,
// but the columns file is 1.9 GB and reading it cover-to-cover from
// File would take 5-15 s and pin a CPU core. The user pasted six
// files into a drop zone — they want feedback in <1 s.
//
// Instead we sample. Read the first ~5 MB of each file, count
// newlines in that slice, and extrapolate to total file size. The
// estimate is within ±5 % for a homogeneous extract (which Rahul's
// .dat files are — every record on a view has the same field
// layout, so the average row size barely drifts across the file).
// We label the result as an estimate so the UI can present it as
// "≈ 9.8M rows" rather than a hard count.

const _SAMPLE_BYTES = 5 * 1024 * 1024; // 5 MiB

export interface PreflightEstimate {
  /** File this estimate refers to. */
  fileName: string;
  /** Bytes on disk (i.e. `File.size`). */
  totalBytes: number;
  /** Estimated total record count, or null if unable to estimate. */
  estimatedRows: number | null;
  /** Sampling range used (for UI tooltip / debugging). */
  sampleBytesUsed: number;
}

// View labels keyed off Rahul's filename prefixes — same map the
// server uses, just for UI rendering (server still does the real
// content-based detection on the bytes).
const _VIEW_LABEL_BY_PREFIX: ReadonlyArray<readonly [string, string]> = [
  ["databasesv_", "Databases"],
  ["tablesv_", "Tables / Views / Procs"],
  ["columnsv_", "Columns"],
  ["indicesv_", "Indices"],
  ["partitioningconstraintsv_", "Partitioning"],
  ["tabletextv_", "DDL text"],
];

export function viewLabelForFile(fileName: string): string | null {
  const lower = fileName.toLowerCase();
  for (const [prefix, label] of _VIEW_LABEL_BY_PREFIX) {
    if (lower.startsWith(prefix)) return label;
  }
  return null;
}

/**
 * Estimate the number of records in a `.dat` extract file by reading
 * a leading sample, counting newlines, and extrapolating to the
 * file's full size. Total cost: one ~5 MB FileReader read per file
 * regardless of how big the file is. Browsers do this off the main
 * thread for `Blob.slice().arrayBuffer()`, so the UI stays
 * responsive even for the 1.9 GB columns file.
 */
export async function estimateRows(file: File): Promise<PreflightEstimate> {
  // Tabletext uses ENDREC as record terminator instead of '\n', so
  // newline counting overcounts wildly (every embedded newline in a
  // DDL fragment becomes a "record"). Skip estimation for that view —
  // the user will still see the file size, which is useful enough,
  // and the server reports the real count after parse.
  const lower = file.name.toLowerCase();
  if (lower.startsWith("tabletextv_")) {
    return {
      fileName: file.name,
      totalBytes: file.size,
      estimatedRows: null,
      sampleBytesUsed: 0,
    };
  }

  if (file.size === 0) {
    return {
      fileName: file.name,
      totalBytes: 0,
      estimatedRows: 0,
      sampleBytesUsed: 0,
    };
  }

  const bytesToRead = Math.min(_SAMPLE_BYTES, file.size);
  const sampleSlice = file.slice(0, bytesToRead);
  const buf = await sampleSlice.arrayBuffer();
  const view = new Uint8Array(buf);

  // Count newlines in the sample. We use UTF-8 bytes directly — '\n'
  // (0x0A) never appears as a continuation byte in any UTF-8 multi-
  // byte sequence, so a raw byte count is exactly the line count.
  let newlines = 0;
  for (let i = 0; i < view.length; i++) {
    if (view[i] === 0x0a) newlines++;
  }

  if (newlines === 0) {
    // Either the file has no records or one giant record without a
    // trailing newline. Either way we can't extrapolate; fall back
    // to "unknown".
    return {
      fileName: file.name,
      totalBytes: file.size,
      estimatedRows: null,
      sampleBytesUsed: bytesToRead,
    };
  }

  // Extrapolate. If we read the entire file (bytesToRead === file.size),
  // newlines IS the exact count, so the multiplication degrades to identity.
  const ratio = file.size / bytesToRead;
  const estimated = Math.round(newlines * ratio);

  return {
    fileName: file.name,
    totalBytes: file.size,
    estimatedRows: estimated,
    sampleBytesUsed: bytesToRead,
  };
}

export async function estimateRowsForAll(
  files: File[],
): Promise<PreflightEstimate[]> {
  // Process in parallel — each file is one async ArrayBuffer read,
  // and modern browsers handle a handful of those concurrently
  // without saturating I/O.
  return Promise.all(files.map(estimateRows));
}

// ──── Pretty-printers used by the panel ────

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function formatRowCount(n: number | null): string {
  if (n == null) return "—";
  if (n < 1_000) return n.toString();
  if (n < 1_000_000) return `${(n / 1_000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}
