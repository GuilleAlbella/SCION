// Two-phase progress UI for the dict-batch import endpoint.
//
// Phase 1 — Uploading: real bytes-on-the-wire % from axios's
//   onUploadProgress. We render an actual filled progress bar plus a
//   live readout (uploaded / total, throughput, ETA).
//
// Phase 2 — Server processing: once the body is fully sent the request
//   is blocked on the server doing parse + bulk-insert + post-ingest.
//   We can't know its true completion %, so we render an indeterminate
//   shimmer bar plus an elapsed-time counter and a stage-aware caption
//   that adapts as time goes on (small extracts finish in seconds; the
//   2.4 GB Transcend-DevTest extract takes several minutes). Designed
//   to make the wait feel intentional rather than frozen.
//
// Self-contained: takes only the values it needs as props, owns no
// network I/O. Caller drives the phase transitions.

"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2, UploadCloud } from "lucide-react";

export type ImportPhase =
  | "idle"
  | "uploading"
  | "processing"
  | "done"
  | "error";

export interface DictImportProgressProps {
  phase: ImportPhase;
  /** Uploaded bytes so far. Only meaningful in `uploading`. */
  loaded?: number;
  /** Total bytes to upload. Only meaningful in `uploading`. */
  total?: number;
  /** Wall-clock millis when the current phase started. Used for ETA
   *  during upload and elapsed counter during processing. */
  phaseStartedAt?: number;
  /** Total bytes the user queued (sum of selected file sizes). Used
   *  as the denominator while axios is still negotiating the request. */
  totalBytesHint?: number;
}

// ──── Formatters ────

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function formatRate(bytesPerSec: number): string {
  if (!isFinite(bytesPerSec) || bytesPerSec <= 0) return "—";
  return `${formatBytes(bytesPerSec)}/s`;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return "<1s";
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  if (m === 0) return `${s}s`;
  if (m < 60) return `${m}m ${s.toString().padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  const mr = m % 60;
  return `${h}h ${mr.toString().padStart(2, "0")}m`;
}

// Captions for the indeterminate processing phase. We escalate the
// message as time passes so the user knows the server is still alive
// and what it's working on. Wording is calibrated to what the Python
// pipeline actually does in `dict_persister.py`: parse small files →
// bulk-insert columns → bulk-insert indices → post-ingest analytics.
function processingCaption(elapsedMs: number, totalBytesHint?: number): string {
  const heavy = (totalBytesHint ?? 0) > 200 * 1024 * 1024;
  if (elapsedMs < 5000) {
    return "Parsing files and validating extraction identity…";
  }
  if (elapsedMs < 30000) {
    return "Persisting databases, tables and partitioning…";
  }
  if (elapsedMs < 120000) {
    return heavy
      ? "Bulk-inserting column metadata in 5 000-row batches. This is the heavy step — sit tight."
      : "Bulk-inserting columns and indices…";
  }
  if (elapsedMs < 300000) {
    return "Still bulk-inserting columns. Multi-million-row extracts can take several minutes on a laptop.";
  }
  return "Running the post-ingest pipeline (graph, metrics, criticality, auto-diff)…";
}

// ──── Component ────

export function DictImportProgress({
  phase,
  loaded,
  total,
  phaseStartedAt,
  totalBytesHint,
}: DictImportProgressProps) {
  // Tick a counter so the elapsed-time readout updates without forcing
  // the parent to re-render. 250 ms is smooth enough to feel live but
  // cheap enough to not waste cycles.
  const [now, setNow] = useState(() => Date.now());
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (phase === "uploading" || phase === "processing") {
      intervalRef.current = setInterval(() => setNow(Date.now()), 250);
      return () => {
        if (intervalRef.current) clearInterval(intervalRef.current);
      };
    }
  }, [phase]);

  if (phase === "idle" || phase === "done" || phase === "error") {
    return null;
  }

  const startedAt = phaseStartedAt ?? now;
  const elapsedMs = now - startedAt;

  // ──── Uploading: real progress ────
  if (phase === "uploading") {
    const denom = total ?? totalBytesHint ?? 0;
    const numer = loaded ?? 0;
    const pct = denom > 0 ? Math.min(100, (numer / denom) * 100) : 0;
    const rate = elapsedMs > 0 ? (numer / elapsedMs) * 1000 : 0;
    const remaining = denom > 0 && rate > 0 ? (denom - numer) / rate : 0;

    return (
      <div
        role="status"
        aria-live="polite"
        aria-label="Uploading dict batch"
        className="mt-4 rounded-xl border border-blue-200 bg-gradient-to-br from-blue-50/80 to-white p-4 shadow-sm"
      >
        <div className="flex items-center gap-2 mb-3">
          <UploadCloud size={16} className="text-blue-600" />
          <div className="text-sm font-semibold text-td-navy">
            Uploading to SCION
          </div>
          <div className="ml-auto text-[11px] font-mono text-blue-700">
            {pct.toFixed(1)}%
          </div>
        </div>

        {/* Determinate bar */}
        <div className="relative h-2 rounded-full bg-blue-100 overflow-hidden">
          <div
            className="absolute inset-y-0 left-0 bg-gradient-to-r from-blue-500 to-blue-600 rounded-full transition-[width] duration-150 ease-out"
            style={{ width: `${pct}%` }}
          />
          {/* Subtle highlight stripe to show motion even on a stalled segment */}
          <div
            className="absolute inset-y-0 right-0 w-8 bg-gradient-to-r from-transparent to-white/40 pointer-events-none"
            style={{ left: `calc(${pct}% - 2rem)`, transition: "left 150ms ease-out" }}
          />
        </div>

        {/* Live readout */}
        <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-x-3 gap-y-1 text-[11px] text-td-gray-dark font-mono">
          <span>
            <span className="text-gray-500">Sent</span>{" "}
            <span className="text-td-navy">{formatBytes(numer)}</span>
            {denom > 0 ? ` / ${formatBytes(denom)}` : ""}
          </span>
          <span>
            <span className="text-gray-500">Speed</span>{" "}
            <span className="text-td-navy">{formatRate(rate)}</span>
          </span>
          <span>
            <span className="text-gray-500">Elapsed</span>{" "}
            <span className="text-td-navy">{formatDuration(elapsedMs)}</span>
          </span>
          <span>
            <span className="text-gray-500">ETA</span>{" "}
            <span className="text-td-navy">
              {remaining > 0 ? formatDuration(remaining * 1000) : "—"}
            </span>
          </span>
        </div>
      </div>
    );
  }

  // ──── Processing: indeterminate shimmer ────
  // Once the bytes are on the server's socket, axios just waits for
  // the response. We can't show real %, so we communicate "the server
  // is working" via a moving stripe + an elapsed-time counter + a
  // stage-aware caption that escalates as wait grows. Doing this is
  // visibly different from "frozen" and matches what the backend is
  // actually doing in dict_persister.py.
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="SCION is processing the import"
      className="mt-4 rounded-xl border border-emerald-200 bg-gradient-to-br from-emerald-50/80 to-white p-4 shadow-sm"
    >
      <div className="flex items-center gap-2 mb-3">
        <Loader2 size={16} className="text-emerald-600 animate-spin" />
        <div className="text-sm font-semibold text-td-navy">
          SCION is processing your batch
        </div>
        <div className="ml-auto text-[11px] font-mono text-emerald-700">
          {formatDuration(elapsedMs)}
        </div>
      </div>

      {/* Indeterminate shimmer bar — keyframes defined inline so this
          file is self-contained and the snapshots page doesn't have
          to know about them. */}
      <style>{`
        @keyframes scionShimmer {
          0%   { transform: translateX(-40%); }
          100% { transform: translateX(140%); }
        }
      `}</style>
      <div className="relative h-2 rounded-full bg-emerald-100 overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 w-1/3 rounded-full bg-gradient-to-r from-transparent via-emerald-500 to-transparent"
          style={{ animation: "scionShimmer 1.6s ease-in-out infinite" }}
        />
      </div>

      {/* Stage-aware caption */}
      <div className="mt-2 flex items-start gap-2 text-[11px] text-td-gray-dark leading-relaxed">
        <CheckCircle2 size={11} className="text-emerald-600 shrink-0 mt-0.5" />
        <span>{processingCaption(elapsedMs, totalBytesHint)}</span>
      </div>

      {/* Helpful subtext after the user has been waiting a while —
          reassures them this is normal for big extracts rather than a
          frozen request. */}
      {elapsedMs > 60000 && (
        <div className="mt-2 text-[10px] text-gray-500 leading-relaxed pl-5">
          Don&apos;t close this tab. Browser progress sits at 100% during
          server processing — that&apos;s expected, the bytes are already
          on SCION and the database is doing the work.
        </div>
      )}
    </div>
  );
}
