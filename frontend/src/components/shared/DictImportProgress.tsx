// Per-step progress UI for the dict-batch import endpoint.
//
// Two simultaneous information channels feed this component:
//
//   1. **Browser upload bytes** (axios `onUploadProgress`) — only
//      meaningful while the request body is in flight. Drives the
//      "Upload" step's sub-progress.
//
//   2. **Server-side progress polling** — the backend writes per-step
//      state (started / running / done / error + caption + fractional
//      progress) into an in-memory dict keyed by an `import_id`
//      generated client-side. The component receives that state via
//      the `serverState` prop, refreshed every ~1 s by the page-level
//      poller.
//
// Render: a vertical checklist where each step shows a status dot,
// label, caption, and an inline progress bar. The currently-running
// step gets a subtle highlight. Done steps show their elapsed time.
// Error steps show the error message inline.
//
// This replaces the previous "indeterminate shimmer + time-based
// caption" approach, which couldn't tell the user *which* phase was
// running, only how long they had been waiting.

"use client";

import { CheckCircle2, Circle, Loader2, UploadCloud, XCircle } from "lucide-react";

import type { ImportProgressState, ImportStep } from "@/lib/api/dict_import";

export type ImportPhase =
  | "idle"
  | "uploading"
  | "processing"
  | "done"
  | "error";

export interface DictImportProgressProps {
  /** Top-level phase, drives whether we render at all and the upload bar. */
  phase: ImportPhase;
  /** Bytes uploaded — only relevant while phase === "uploading". */
  loaded?: number;
  /** Total bytes to upload. */
  total?: number;
  /** Wall-clock millis when uploading started. Used for ETA. */
  uploadingStartedAt?: number;
  /** Latest server-side state from the polling channel. May be null
   *  during the very brief window between clicking Upload and the
   *  first successful poll. */
  serverState?: ImportProgressState | null;
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

// ──── Step row ────

interface StepRowProps {
  step: ImportStep;
  /** Optional override for the inline progress (used by the upload step
   *  to feed in real bytes-on-the-wire %, since the server doesn't
   *  see the upload progress directly). */
  liveProgress?: number;
  /** Optional override for the caption (same reason). */
  liveCaption?: string;
}

function StepRow({ step, liveProgress, liveCaption }: StepRowProps) {
  const status = step.status;
  const fraction = liveProgress ?? step.progress ?? null;
  const caption = liveCaption ?? step.caption ?? null;

  // Pick an icon + colour scheme based on status. We keep these tight
  // and consistent across the four states so the user can scan the
  // list at a glance.
  let Icon = Circle;
  let iconClass = "text-gray-300";
  let labelClass = "text-gray-500";
  let bgClass = "";
  let barFill = "bg-gray-200";

  if (status === "running") {
    Icon = Loader2;
    iconClass = "text-blue-600 animate-spin";
    labelClass = "text-td-navy font-semibold";
    bgClass = "bg-blue-50/40";
    barFill = "bg-gradient-to-r from-blue-500 to-blue-600";
  } else if (status === "done") {
    Icon = CheckCircle2;
    iconClass = "text-emerald-600";
    labelClass = "text-td-navy";
    barFill = "bg-emerald-500";
  } else if (status === "error") {
    Icon = XCircle;
    iconClass = "text-red-600";
    labelClass = "text-red-700 font-semibold";
    bgClass = "bg-red-50/60";
    barFill = "bg-red-500";
  }

  return (
    <div className={`flex items-start gap-2 px-3 py-2 ${bgClass}`}>
      <Icon size={14} className={`shrink-0 mt-0.5 ${iconClass}`} />

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className={`text-[12px] ${labelClass}`}>{step.label}</span>
          {caption && (
            <span className="text-[10px] text-gray-500 truncate font-mono">
              {caption}
            </span>
          )}
        </div>

        {/* Determinate progress bar when we have a fraction; subtle
            indeterminate shimmer when running without one; nothing
            for pending or done. */}
        {status === "running" && fraction != null && (
          <div className="mt-1 h-1 rounded-full bg-blue-100 overflow-hidden">
            <div
              className={`h-full ${barFill} transition-[width] duration-150 ease-out`}
              style={{ width: `${Math.min(100, fraction * 100).toFixed(1)}%` }}
            />
          </div>
        )}
        {status === "running" && fraction == null && (
          <>
            <style>{`
              @keyframes scionShimmer {
                0%   { transform: translateX(-40%); }
                100% { transform: translateX(140%); }
              }
            `}</style>
            <div className="mt-1 relative h-1 rounded-full bg-blue-100 overflow-hidden">
              <div
                className="absolute inset-y-0 left-0 w-1/3 rounded-full bg-gradient-to-r from-transparent via-blue-500 to-transparent"
                style={{ animation: "scionShimmer 1.6s ease-in-out infinite" }}
              />
            </div>
          </>
        )}
      </div>

      {/* Per-step elapsed time, fixed-width so the column aligns. */}
      <span className="text-[10px] text-gray-500 font-mono w-14 text-right shrink-0 mt-0.5">
        {step.elapsed_seconds != null
          ? formatDuration(step.elapsed_seconds * 1000)
          : ""}
      </span>
    </div>
  );
}

// ──── Component ────

export function DictImportProgress({
  phase,
  loaded,
  total,
  uploadingStartedAt,
  serverState,
}: DictImportProgressProps) {
  if (phase === "idle" || phase === "done" || phase === "error") {
    return null;
  }

  // Compute the live upload-bar values that override the server-side
  // "upload" step while the body is still going up the wire. The
  // server only knows "upload" started — it can't see the in-flight
  // byte counts.
  let liveUploadProgress: number | undefined;
  let liveUploadCaption: string | undefined;
  if (phase === "uploading" && total && total > 0) {
    const numer = loaded ?? 0;
    const pct = numer / total;
    const elapsedMs =
      uploadingStartedAt !== undefined ? Date.now() - uploadingStartedAt : 0;
    const rate = elapsedMs > 0 ? (numer / elapsedMs) * 1000 : 0;
    liveUploadProgress = pct;
    liveUploadCaption = `${formatBytes(numer)} / ${formatBytes(total)} · ${formatRate(rate)}`;
  }

  // If we have server-side state, use its step list as the source of
  // truth (it knows about every step, including ones that haven't
  // started yet). Until the first poll lands we fall back to a
  // synthetic "Uploading…" placeholder so the panel never goes blank
  // between clicking the button and the first response.
  const steps: ImportStep[] = serverState?.steps ?? [
    {
      name: "upload",
      label: "Upload files",
      status: "running",
      progress: liveUploadProgress ?? null,
      caption: liveUploadCaption ?? "starting…",
      elapsed_seconds:
        uploadingStartedAt !== undefined
          ? (Date.now() - uploadingStartedAt) / 1000
          : null,
    },
  ];

  // Header visual treatment: blue while uploading or processing,
  // green on success, red on error. The component returns `null` for
  // idle / done / error at the top, so this is always blue-ish here
  // — but kept as an explicit prop so future callers can override.
  const headerColor =
    serverState?.status === "error" ? "border-red-200 bg-red-50/50" :
    "border-blue-200 bg-gradient-to-br from-blue-50/80 to-white";

  const totalElapsed = serverState?.total_elapsed_seconds ?? null;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Dict import progress"
      className={`mt-4 rounded-xl border ${headerColor} shadow-sm overflow-hidden`}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-blue-100">
        <UploadCloud size={16} className="text-blue-600" />
        <div className="text-sm font-semibold text-td-navy">
          Importing dict batch
        </div>
        <div className="ml-auto text-[11px] font-mono text-blue-700">
          {totalElapsed != null
            ? formatDuration(totalElapsed * 1000)
            : phase === "uploading" && uploadingStartedAt !== undefined
              ? formatDuration(Date.now() - uploadingStartedAt)
              : ""}
        </div>
      </div>

      {/* Step list */}
      <div className="divide-y divide-gray-100">
        {steps.map((s) => (
          <StepRow
            key={s.name}
            step={s}
            liveProgress={s.name === "upload" ? liveUploadProgress : undefined}
            liveCaption={s.name === "upload" ? liveUploadCaption : undefined}
          />
        ))}
      </div>

      {/* Server error message when the import bombed mid-pipeline. */}
      {serverState?.status === "error" && serverState.error_message && (
        <div className="px-4 py-2 border-t border-red-200 bg-red-50/80 text-[11px] text-red-900 font-mono whitespace-pre-wrap">
          {serverState.error_message}
        </div>
      )}

      {/* Footer reassurance during the long server-processing phase.
          Kept short — the per-step labels above are the main story. */}
      {phase === "processing" && (
        <div className="px-4 py-2 border-t border-blue-100 text-[10px] text-gray-500 leading-relaxed">
          Don&apos;t close this tab — the database is doing the work. Browser
          upload progress sits at 100% during server processing; that&apos;s
          expected.
        </div>
      )}
    </div>
  );
}
