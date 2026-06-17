"use client";

import { useState, useRef, useEffect } from "react";
import { mutate } from "swr";
import PageShell from "@/components/layout/PageShell";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { useSelection } from "@/lib/SelectionContext";
import { createSnapshot, deleteSnapshot } from "@/lib/api/snapshots";
import { previewParserImport, confirmParserImport } from "@/lib/api/parser_import";
import {
  cancelImport,
  importDictBatch,
  makeImportId,
  pollImportProgress,
  type DictImportResponse,
  type ImportProgressState,
} from "@/lib/api/dict_import";
import type { ParserImportResponse } from "@/lib/api/types";
import { Plus, Check, Upload, FileJson, FileText, Inbox, CheckCircle2, X, Trash2, AlertTriangle, ShieldCheck, AlertCircle, FolderSync, Database, GitBranch, Activity } from "lucide-react";
import { scanShare, importFromShare, type ShareScanResponse, type ShareImportResponse } from "@/lib/api/share_import";
import { useToast } from "@/components/shared/ToastProvider";
import { DictImportProgress, type ImportPhase } from "@/components/shared/DictImportProgress";
import {
  estimateRowsForAll,
  formatBytes,
  formatRowCount,
  viewLabelForFile,
  type PreflightEstimate,
} from "@/lib/dict_preflight";

export default function SnapshotsPage() {
  const { data, error, isLoading } = useSnapshots();
  const { activeSnapshotId, setActiveSnapshotId } = useSelection();
  const { toast } = useToast();
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Delete-confirmation flow uses type-to-confirm: the button stays disabled
  // until the user types the exact numeric snapshot ID. This is intentional
  // friction — deletes cascade across diffs, impacts, and TAISA reasoning.
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);

  // ──── Parser JSON import state ────
  // Hidden file input triggered by a button, then a preview panel before
  // the user confirms the actual import. Two-phase flow:
  //   1. POST the raw JSON with dry_run=true to get an IngestionReport
  //   2. Show counts/warnings, then on "Confirm" POST again with dry_run=false
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  // Raw parsed JSON kept so the confirm call can re-POST the same payload.
  const [importPayload, setImportPayload] = useState<unknown>(null);
  const [importReport, setImportReport] = useState<ParserImportResponse | null>(null);
  const [importing, setImporting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  // ──── Dict batch import state (v1.12+) ────
  // Multipart upload of up to 6 .dat files in any order. The server
  // detects each file's content type and validates batch consistency
  // (same source + run_id + temporal coherence) before persisting one
  // snapshot keyed by `extract_run_id`.
  //
  // We keep this separate from the parser flow because:
  //   - parser is JSON, single file, two-phase (preview → confirm)
  //   - dict is .dat, multi-file, single-shot (server is idempotent so
  //     no preview is needed — re-uploading is safe)
  const dictInputRef = useRef<HTMLInputElement>(null);
  const [dictPanelOpen, setDictPanelOpen] = useState(false);
  const [dictFiles, setDictFiles] = useState<File[]>([]);
  const [dictUploading, setDictUploading] = useState(false);
  const [dictResult, setDictResult] = useState<DictImportResponse | null>(null);
  const [dictError, setDictError] = useState<string | null>(null);

  // Two-phase progress UI for the dict batch upload. `phase` drives which
  // bar (real % during uploading, indeterminate during processing) the
  // DictImportProgress component renders. Bytes counters are only
  // meaningful while phase === "uploading"; we keep them in state so
  // the readout stays consistent across re-renders without prop drilling.
  const [dictPhase, setDictPhase] = useState<ImportPhase>("idle");
  const [dictUploadedBytes, setDictUploadedBytes] = useState(0);
  const [dictTotalBytes, setDictTotalBytes] = useState<number | undefined>(undefined);
  const [dictPhaseStartedAt, setDictPhaseStartedAt] = useState<number | undefined>(undefined);

  // Pre-flight row estimates per dropped file. Empty until the user
  // adds files; populated asynchronously by `estimateRowsForAll` so
  // the panel can show "Columns ≈ 9.8M rows (1.9 GB)" before the
  // upload starts. Keyed by `${name}::${size}` (same shape as the
  // dedupe key in `addDictFiles`) so a row can be found in O(1)
  // when rendering the per-file list.
  const [dictPreflight, setDictPreflight] = useState<
    Map<string, PreflightEstimate>
  >(new Map());

  // Latest server-side per-step state, refreshed by the polling
  // channel that runs in parallel with the long POST. `null` until
  // the first poll lands; we render a synthetic upload-only step
  // until then so the checklist never goes blank.
  const [dictServerProgress, setDictServerProgress] =
    useState<ImportProgressState | null>(null);

  // Tracks the in-flight import so the Cancel button can target it.
  // `null` whenever no import is running; populated for the lifetime
  // of `handleDictUpload`. We keep it in state (not a ref) so the
  // Cancel button's enabled/disabled state can re-render as the
  // upload starts and finishes.
  const [dictActiveImportId, setDictActiveImportId] = useState<string | null>(
    null,
  );
  const [dictCancelling, setDictCancelling] = useState(false);

  // ──── Share import state ────
  const [sharePanelOpen, setSharePanelOpen] = useState(false);
  const [shareScan, setShareScan] = useState<ShareScanResponse | null>(null);
  const [shareScanning, setShareScanning] = useState(false);
  const [shareImporting, setShareImporting] = useState(false);
  const [shareResult, setShareResult] = useState<ShareImportResponse | null>(null);
  const [shareError, setShareError] = useState<string | null>(null);

  // ── Resume in-flight import after page navigation ─────────────────
  // The user can navigate away from Snapshots while a dict-import is
  // running (the long POST keeps going in the browser background).
  // On unmount all useState is lost, so returning to Snapshots would
  // show a blank page with no indication that an import is running.
  //
  // Fix: we persist the active import_id + phase start time in
  // sessionStorage. On mount we check for a saved entry; if found we
  // reopen the panel, switch to "processing" phase and restart the
  // polling channel — the server-side progress is still available as
  // long as the server is running.  When the import finishes (or the
  // user cancels / an error occurs) the entry is removed.
  //
  // The pollAbort ref lets the cleanup function stop the resumed poll
  // channel when the component unmounts again.
  const resumePollAbortRef = useRef<AbortController | null>(null);

  const _STORAGE_KEY = "scion_active_import";

  useEffect(() => {
    const raw = sessionStorage.getItem(_STORAGE_KEY);
    if (!raw) return;
    let parsed: { importId: string; startedAt: number };
    try {
      parsed = JSON.parse(raw);
    } catch {
      sessionStorage.removeItem(_STORAGE_KEY);
      return;
    }
    const { importId, startedAt } = parsed;

    // Re-open the panel in processing state — we don't have the file
    // list any more but the checklist (driven by server progress) gives
    // the user all the relevant info.
    setDictPanelOpen(true);
    setDictPhase("processing");
    setDictUploading(true);
    setDictActiveImportId(importId);
    setDictPhaseStartedAt(startedAt);

    const ac = new AbortController();
    resumePollAbortRef.current = ac;

    pollImportProgress(
      importId,
      (state) => {
        setDictServerProgress(state);
        if (
          state.status === "done" ||
          state.status === "error" ||
          state.status === "cancelled"
        ) {
          sessionStorage.removeItem(_STORAGE_KEY);
          setDictPhase(state.status === "done" ? "done" : "error");
          setDictUploading(false);
          setDictActiveImportId(null);
          ac.abort();
          if (state.status === "done") {
            void mutate("snapshots");
          }
        }
      },
      ac.signal,
    );

    return () => {
      ac.abort();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-open the share import panel when the notification bell sends
  // the user here with ?autoImport=true.
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("autoImport") === "true") {
        openSharePanel();
      }
    }
    // Run once on mount — router.push from the bell always navigates here fresh
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openSharePanel() {
    setSharePanelOpen(true);
    setShareResult(null);
    setShareError(null);
    setShareScanning(true);
    try {
      const scan = await scanShare();
      setShareScan(scan);
    } catch (e: unknown) {
      setShareError(e instanceof Error ? e.message : "Could not reach share");
    } finally {
      setShareScanning(false);
    }
  }

  async function handleShareImport() {
    setShareImporting(true);
    setShareError(null);
    try {
      const result = await importFromShare();
      setShareResult(result);
      await mutate("snapshots");
      setActiveSnapshotId(result.snapshot_id);
      const lineagePart = result.lineage_attached
        ? ` + ${result.lineage_tables} lineage tables, ${result.lineage_edges} edges`
        : "";
      toast(
        `Snapshot #${result.snapshot_id} created from share. ` +
        `${result.dict_result.tables_created} tables, ${result.dict_result.columns_created} columns${lineagePart}.`,
        "success"
      );
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "response" in e
        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Import failed"
        : e instanceof Error ? e.message : "Import failed";
      setShareError(msg);
    } finally {
      setShareImporting(false);
    }
  }

  function clearShareImport() {
    setSharePanelOpen(false);
    setShareScan(null);
    setShareResult(null);
    setShareError(null);
  }

  async function handleCreate() {
    setCreating(true);
    setCreateError(null);
    try {
      await createSnapshot();
      await mutate("snapshots");
    } catch (e: unknown) {
      setCreateError(e instanceof Error ? e.message : "Failed to create snapshot");
    } finally {
      setCreating(false);
    }
  }

  // Picking a file kicks off the dry-run automatically — users always see
  // the preview report before they get a "Confirm" button. This way they
  // never accidentally persist a garbled payload.
  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setImportFile(file);
    setImportError(null);
    setImportReport(null);
    setImportPayload(null);

    const reader = new FileReader();
    reader.onload = async (ev) => {
      let json: unknown;
      try {
        json = JSON.parse(ev.target?.result as string);
      } catch {
        setImportError("Invalid JSON file. Please select a valid parser output file.");
        setImportFile(null);
        return;
      }
      setImportPayload(json);
      await runDryRun(json);
    };
    reader.readAsText(file);
  }

  async function runDryRun(payload: unknown) {
    setImporting(true);
    setImportError(null);
    try {
      const report = await previewParserImport(payload);
      setImportReport(report);
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "response" in e
        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Preview failed"
        : e instanceof Error ? e.message : "Preview failed";
      setImportError(msg);
    } finally {
      setImporting(false);
    }
  }

  async function handleConfirmImport() {
    if (!importPayload) return;
    setConfirming(true);
    setImportError(null);
    try {
      const report = await confirmParserImport(importPayload);
      await mutate("snapshots");
      if (report.snapshot_id != null) {
        setActiveSnapshotId(report.snapshot_id);
        toast(
          `Snapshot #${report.snapshot_id} created from parser feed. ` +
          `${report.persisted_counts.tables ?? 0} tables, ${report.persisted_counts.columns ?? 0} columns persisted.`,
          "success"
        );
      } else {
        toast("Import completed but no snapshot_id returned.", "error");
      }
      clearImport();
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "response" in e
        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Import failed"
        : e instanceof Error ? e.message : "Import failed";
      setImportError(msg);
    } finally {
      setConfirming(false);
    }
  }

  function clearImport() {
    setImportFile(null);
    setImportPayload(null);
    setImportReport(null);
    setImportError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  // ──── Dict batch helpers ────

  function addDictFiles(incoming: FileList | File[]) {
    const arr = Array.from(incoming);
    const key = (f: File) => `${f.name}::${f.size}`;
    setDictFiles((prev) => {
      // Dedupe by name+size — dragging the same file twice shouldn't
      // double up. The browser's File API gives a new object on each
      // drag so identity-based dedup wouldn't work.
      const seen = new Set(prev.map(key));
      const next = [...prev];
      for (const f of arr) if (!seen.has(key(f))) next.push(f);
      return next;
    });
    setDictResult(null);
    setDictError(null);
    // Estimation is kicked off by the `useEffect` below — driving it
    // from a dependency on `dictFiles` is more robust than firing
    // here, where capturing the just-merged file list (vs the stale
    // current-render value of `dictFiles`) is fiddly.
  }

  // Pre-flight row-count estimation. Whenever `dictFiles` changes,
  // estimate any file we haven't seen yet. Cleanup via the cancel
  // flag so a rapid drop-then-clear doesn't leak a stale promise
  // that overwrites fresh state.
  useEffect(() => {
    const filesToEstimate = dictFiles.filter(
      (f) => !dictPreflight.has(`${f.name}::${f.size}`),
    );
    if (filesToEstimate.length === 0) return;
    // eslint-disable-next-line no-console
    console.info(
      `[dict-import] pre-flight estimating ${filesToEstimate.length} file(s)`,
      filesToEstimate.map((f) => `${f.name} (${(f.size / 1024 / 1024).toFixed(1)} MB)`),
    );

    let cancelled = false;
    void estimateRowsForAll(filesToEstimate)
      .then((estimates) => {
        if (cancelled) return;
        // eslint-disable-next-line no-console
        console.info(
          `[dict-import] pre-flight resolved ${estimates.length} estimate(s):`,
          estimates.map((e) => ({
            file: e.fileName,
            rows: e.estimatedRows,
            bytes: e.totalBytes,
          })),
        );
        setDictPreflight((prev) => {
          const next = new Map(prev);
          for (const est of estimates) {
            next.set(`${est.fileName}::${est.totalBytes}`, est);
          }
          return next;
        });
      })
      .catch((err) => {
        // Pre-flight is purely informational — failure should never
        // block the user from clicking Upload. Log and move on.
        // eslint-disable-next-line no-console
        console.warn("[dict-import] pre-flight estimation failed:", err);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dictFiles]);

  function removeDictFile(idx: number) {
    setDictFiles((prev) => prev.filter((_, i) => i !== idx));
  }

  function clearDictImport() {
    setDictFiles([]);
    setDictResult(null);
    setDictError(null);
    setDictPanelOpen(false);
    setDictPhase("idle");
    setDictUploadedBytes(0);
    setDictTotalBytes(undefined);
    setDictPhaseStartedAt(undefined);
    setDictPreflight(new Map());
    setDictServerProgress(null);
    setDictActiveImportId(null);
    setDictCancelling(false);
    if (dictInputRef.current) dictInputRef.current.value = "";
  }

  async function handleDictCancel() {
    if (dictActiveImportId == null || dictCancelling) return;
    // eslint-disable-next-line no-console
    console.info(
      `[dict-import] Cancel button clicked, requesting cancellation of ${dictActiveImportId}`,
    );
    setDictCancelling(true);
    try {
      // Tell the server to flag the in-flight import for cancellation.
      // The persist-phase hot loop polls this flag at heartbeat
      // boundaries (~6 s) and rolls back when it sees it set. The
      // POST resolves with HTTP 499 — handled in handleDictUpload's
      // catch block as a "cancelled" outcome rather than an error.
      const ok = await cancelImport(dictActiveImportId);
      if (ok) {
        toast(
          "Cancellation requested. The import will roll back at the next checkpoint (within ~6 seconds).",
          "info",
        );
      } else {
        toast(
          "Nothing to cancel — the import already finished or hasn't registered yet.",
          "info",
        );
        setDictCancelling(false);
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Cancel failed";
      // eslint-disable-next-line no-console
      console.error("[dict-import] Cancel POST threw:", e);
      toast(`Cancel failed: ${msg}`, "error");
      setDictCancelling(false);
    }
  }

  async function handleDictUpload() {
    if (dictFiles.length === 0) return;

    // Sum file sizes up-front so the progress bar has a denominator
    // even before axios negotiates the request — otherwise the bar
    // sits at 0% with "—/—" for the first few hundred ms which feels
    // broken to the user. The browser will fill in the precise value
    // once the upload starts.
    const totalHint = dictFiles.reduce((s, f) => s + f.size, 0);

    // Generate one import_id for this attempt and start polling
    // server-side progress in parallel with the long POST. The
    // AbortController lets us cancel the polling cleanly when the
    // POST resolves (or errors) — without it we'd leak a setTimeout
    // chain that keeps hitting the server forever.
    const importId = makeImportId();
    const pollAbort = new AbortController();
    pollImportProgress(
      importId,
      (state) => setDictServerProgress(state),
      pollAbort.signal,
    );

    setDictUploading(true);
    setDictError(null);
    setDictResult(null);
    setDictServerProgress(null);
    setDictPhase("uploading");
    setDictUploadedBytes(0);
    setDictTotalBytes(totalHint);
    const startedAt = Date.now();
    setDictPhaseStartedAt(startedAt);
    setDictActiveImportId(importId);
    setDictCancelling(false);

    // Persist so we can resume if the user navigates away and returns.
    sessionStorage.setItem(
      _STORAGE_KEY,
      JSON.stringify({ importId, startedAt }),
    );

    try {
      const r = await importDictBatch(dictFiles, false, (e) => {
        // axios fires this on every chunk. We update the bytes counters
        // and, the moment the body is fully sent, switch the phase to
        // "processing" so the UI swaps from a determinate to an
        // indeterminate bar. The processing phase is what dominates
        // the wall time on multi-GB extracts (server doing parse +
        // bulk-insert + post-ingest), so getting the transition right
        // is what makes the overall UX feel responsive.
        setDictUploadedBytes(e.loaded);
        if (e.total !== undefined) setDictTotalBytes(e.total);
        if (e.uploadComplete) {
          setDictPhase((prev) => {
            if (prev === "uploading") {
              setDictPhaseStartedAt(Date.now());
              return "processing";
            }
            return prev;
          });
        }
      }, importId);
      setDictResult(r);
      setDictPhase("done");
      sessionStorage.removeItem(_STORAGE_KEY);
      // Refresh snapshot list so the new snapshot shows up below.
      // Keep panel open so user sees the success card with counts.
      await mutate("snapshots");
      if (r.snapshot_id != null && !r.skipped_existing) {
        setActiveSnapshotId(r.snapshot_id);
        toast(
          `Snapshot #${r.snapshot_id} created from dict batch (${r.source_system_name}). ` +
            `${r.tables_created} tables, ${r.columns_created} columns persisted.`,
          "success"
        );
      } else if (r.skipped_existing) {
        toast(
          `Idempotent: snapshot #${r.snapshot_id} already exists for this extract_run_id.`,
          "success"
        );
      }
    } catch (e: unknown) {
      // Backend returns batch-validator messages multi-line; preserve them.
      let msg = "Upload failed.";
      let httpStatus: number | undefined;
      if (typeof e === "object" && e !== null) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const ax = e as any;
        httpStatus = ax.response?.status;
        if (ax.response?.data?.detail) msg = String(ax.response.data.detail);
        else if (ax.message) msg = ax.message;
      }
      // HTTP 499 is our convention for "client cancelled the import"
      // (handler raised ImportCancelled, transaction rolled back). We
      // treat it as a clean exit rather than an error — the toast in
      // handleDictCancel already told the user what's happening.
      if (httpStatus === 499) {
        setDictPhase("idle");
        sessionStorage.removeItem(_STORAGE_KEY);
        toast("Import cancelled. No data was persisted.", "info");
        // Wipe the panel back to "ready to drop new files" so the
        // user can retry without any leftover progress UI.
        setDictFiles([]);
        setDictPreflight(new Map());
        setDictServerProgress(null);
      } else {
        setDictError(msg);
        setDictPhase("error");
        sessionStorage.removeItem(_STORAGE_KEY);
      }
    } finally {
      // Always stop the parallel polling channel — without this the
      // browser would keep hitting `/progress` long after the import
      // finished, eventually 404-ing as the entry gets evicted from
      // the in-memory cache.
      pollAbort.abort();
      setDictUploading(false);
      setDictActiveImportId(null);
      setDictCancelling(false);
    }
  }

  // ──── Dict batch coverage check ────
  // Mirrors the 6 view filenames Rahul's extractor produces. Pure
  // presentation — the server accepts partial batches; this just gives
  // the user a friendly "you have X of 6" hint.
  const DICT_EXPECTED = [
    { prefix: "databasesv_", label: "Databases" },
    { prefix: "tablesv_", label: "Tables / Views / Procs" },
    { prefix: "columnsv_", label: "Columns" },
    { prefix: "indicesv_", label: "Indices" },
    { prefix: "partitioningconstraintsv_", label: "Partitioning" },
    { prefix: "tabletextv_", label: "DDL text" },
  ];
  const dictCoverage = DICT_EXPECTED.map((spec) => ({
    ...spec,
    matched: dictFiles.some((f) => f.name.toLowerCase().startsWith(spec.prefix)),
  }));
  const dictMatchedCount = dictCoverage.filter((c) => c.matched).length;

  async function handleDelete() {
    if (deleteTarget == null) return;
    setDeleting(true);
    try {
      const res = await deleteSnapshot(deleteTarget);
      // Build a friendly toast that includes the disk space reclaimed
      // by the post-delete VACUUM when applicable. Falls back to the
      // old "X tables, Y changes removed" wording when VACUUM was
      // skipped or failed.
      const freed = res.vacuum?.bytes_freed;
      const freedFragment =
        freed != null && freed > 0
          ? ` Freed ${formatBytes(freed)} on disk.`
          : "";
      toast(
        `Snapshot #${res.deleted_snapshot_id} deleted. ` +
          `${res.cascade.tables} tables, ${res.cascade.columns} columns, ` +
          `${res.cascade.changes} changes removed.${freedFragment}`,
        "success"
      );
      await mutate("snapshots");
      if (activeSnapshotId === deleteTarget) setActiveSnapshotId(null);
      setDeleteTarget(null);
      setConfirmText("");
    } catch (e: unknown) {
      const msg = e && typeof e === "object" && "response" in e
        ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Delete failed"
        : e instanceof Error ? e.message : "Delete failed";
      toast(msg, "error");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <PageShell title="Snapshots" subtitle="Metadata state versions">
      {/* Page-level intro explaining what a snapshot is and the two ways to
          create one. Kept at the top so first-time users don't have to infer
          the concept from button labels. */}
      <div className="bg-blue-50/40 border border-blue-100 rounded-lg px-3 py-2 mb-4 flex items-start gap-2">
        <svg className="text-blue-500 shrink-0 mt-0.5" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
        <p className="text-[11px] text-td-gray-dark leading-relaxed">
          A <strong>snapshot</strong> is a frozen, hashed copy of the warehouse&apos;s
          structural state at a point in time — databases, tables, views, columns,
          types, nullability. Everything else in SCION (diffs, impact, intelligence,
          criticality) compares two snapshots to detect what moved. Three ways to
          create one: <strong>Capture Live Snapshot</strong> (reads the local
          backing DB; demo only),{" "}
          <strong>Import from Parser</strong> (DataDNA parser JSON feed, two-phase
          preview → confirm), or <strong>Import Dict Batch</strong> (the 6-file
          .dat extract from the data-dictionary pipeline, idempotent by{" "}
          <code className="font-mono">extract_run_id</code>). Only the latest
          snapshot can be deleted; older ones are immutable to protect the diff history.
        </p>
      </div>

      {/* Action buttons — four import paths in one row.
          Order: share (primary for prod) → dict batch → parser JSON → capture live. */}
      <div className="flex gap-3 justify-end mb-4 flex-wrap">
        <button
          onClick={() => sharePanelOpen ? clearShareImport() : openSharePanel()}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            sharePanelOpen
              ? "bg-emerald-600 text-white"
              : "bg-emerald-500 text-white hover:bg-emerald-600"
          }`}
        >
          <FolderSync size={16} />
          Import from Share
        </button>
        <button
          onClick={() => setDictPanelOpen((o) => !o)}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            dictPanelOpen
              ? "bg-blue-600 text-white"
              : "bg-blue-500 text-white hover:bg-blue-600"
          }`}
        >
          <Inbox size={16} />
          Import Dict Batch
        </button>
        <button
          onClick={() => fileInputRef.current?.click()}
          className="flex items-center gap-2 bg-td-orange text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-td-orange/90 transition-colors"
        >
          <Upload size={16} />
          Import from Parser
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          onChange={handleFileSelect}
          className="hidden"
        />
        <button
          onClick={handleCreate}
          disabled={creating}
          className="flex items-center gap-2 bg-td-navy text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-td-navy-light disabled:opacity-50 transition-colors"
        >
          <Plus size={16} />
          {creating ? "Creating..." : "Capture Live Snapshot"}
        </button>
      </div>

      {/* ──── Share import panel ────
          Reads files directly from the server-side CIFS mount — no upload
          needed. Shows a pre-flight scan of what's available, then lets
          the user import everything in one click. */}
      {sharePanelOpen && (
        <div className="bg-white rounded-xl shadow-sm border-2 border-emerald-500 p-5 mb-6">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <FolderSync size={20} className="text-emerald-600" />
              <h3 className="text-sm font-semibold text-td-navy">Import from Share</h3>
            </div>
            <button onClick={clearShareImport} className="text-td-gray-dark hover:text-td-navy">
              <X size={16} />
            </button>
          </div>

          <p className="text-[11px] text-td-gray-dark mb-4">
            Imports all available files from the server-side share in one unified snapshot.
            Dict structure, PDCR usage data, and DBQL lineage are all combined into
            a single snapshot — no file upload required.
          </p>

          {shareScanning && (
            <div className="text-xs text-td-gray-dark py-3">Scanning share…</div>
          )}

          {shareScan && !shareScanning && (
            <>
              {!shareScan.share_available ? (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-3 text-xs text-amber-900">
                  Share not reachable at <code className="font-mono">{shareScan.share_path}</code>.
                  Check that the CIFS mount is active on the server.
                </div>
              ) : (
                <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 mb-4">
                  <div className="text-[10px] font-semibold text-td-gray-dark uppercase tracking-wider mb-2">
                    Files available in share
                  </div>
                  <div className="space-y-1.5">
                    <ShareFileRow
                      icon={<Database size={11} />}
                      label="Data Dictionary"
                      files={shareScan.dict_files}
                    />
                    <ShareFileRow
                      icon={<GitBranch size={11} />}
                      label="Data Lineage"
                      files={shareScan.lineage_files}
                    />
                    <ShareFileRow
                      icon={<Activity size={11} />}
                      label="Object Usage (PDCR)"
                      files={shareScan.pdcr_files}
                    />
                  </div>
                </div>
              )}

              {shareScan.share_available && !shareResult && (
                <button
                  onClick={handleShareImport}
                  disabled={shareImporting || shareScan.dict_files.length === 0}
                  className="flex items-center gap-2 bg-emerald-500 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-emerald-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                >
                  <Upload size={14} />
                  {shareImporting ? "Importing…" : "Import all"}
                </button>
              )}
            </>
          )}

          {shareResult && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <CheckCircle2 size={14} className="text-emerald-600" />
                <div className="text-sm font-semibold text-td-navy">
                  Snapshot #{shareResult.snapshot_id} created
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-[11px] mb-2">
                <SummaryStat label="Schemas" value={String(shareResult.dict_result.schemas_created)} />
                <SummaryStat label="Tables" value={String(shareResult.dict_result.tables_created)} />
                <SummaryStat label="Columns" value={String(shareResult.dict_result.columns_created)} />
                {shareResult.lineage_attached && (
                  <>
                    <SummaryStat label="Lineage tables" value={String(shareResult.lineage_tables)} />
                    <SummaryStat label="Lineage edges" value={String(shareResult.lineage_edges)} />
                  </>
                )}
                {(shareResult.dict_result.object_usage_inserted ?? 0) > 0 && (
                  <SummaryStat label="Usage rows" value={String(shareResult.dict_result.object_usage_inserted)} />
                )}
              </div>
              {shareResult.lineage_warnings.length > 0 && (
                <ul className="text-[10px] text-amber-700 space-y-0.5 mb-2">
                  {shareResult.lineage_warnings.map((w, i) => (
                    <li key={i}>⚠ {w}</li>
                  ))}
                </ul>
              )}
              <button onClick={clearShareImport} className="text-xs text-emerald-700 hover:underline">
                Done — close panel
              </button>
            </div>
          )}

          {shareError && (
            <div className="mt-3 bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700">
              {shareError}
            </div>
          )}
        </div>
      )}

      {/* ──── Dict batch import panel ────
          Toggled open by the "Import Dict Batch" button. Drag-drop or
          click-to-pick up to 6 .dat files; coverage indicator shows
          which views are covered; server validates batch consistency
          on upload. Same UX as the standalone /import page used to
          have, consolidated into Snapshots in v1.13.02. */}
      {dictPanelOpen && (
        <div className="bg-white rounded-xl shadow-sm border-2 border-blue-500 p-5 mb-6">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Inbox size={20} className="text-blue-500" />
              <h3 className="text-sm font-semibold text-td-navy">
                Data Dictionary Batch Import
              </h3>
            </div>
            <button onClick={clearDictImport} className="text-td-gray-dark hover:text-td-navy">
              <X size={16} />
            </button>
          </div>

          <p className="text-[11px] text-td-gray-dark mb-3">
            Drop the <strong>.dat files</strong> from one extraction run (any order).
            All files must share the same <code className="font-mono">source_system_name</code> and{" "}
            <code className="font-mono">extract_run_id</code>; mixed-batch uploads are rejected
            server-side with a clear diff. Re-uploading the same batch is idempotent.
          </p>

          {/* Drop zone */}
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (e.dataTransfer.files.length > 0) addDictFiles(e.dataTransfer.files);
            }}
            onClick={() => dictInputRef.current?.click()}
            className="border-2 border-dashed border-gray-300 hover:border-blue-400 rounded-lg p-6 text-center cursor-pointer transition-colors bg-gray-50/40"
          >
            <Inbox size={24} className="mx-auto mb-2 text-gray-400" />
            <p className="text-sm font-medium text-td-navy">
              Drop .dat files here, or click to pick
            </p>
            <p className="text-[10px] text-td-gray-dark mt-1">
              Content type is detected server-side (filename is a tiebreaker only)
            </p>
            <input
              ref={dictInputRef}
              type="file"
              multiple
              // `accept=".dat"` filters the OS picker to extraction
              // outputs only — without it the user can pick any
              // file (image, PDF, etc) and the server rejection
              // happens far too late. Drag-drop bypasses this filter
              // (it's an OS limitation, not ours), so the server-side
              // format detector remains the source of truth; this
              // just removes the obvious foot-gun for click-to-pick.
              accept=".dat"
              onChange={(e) => {
                if (e.target.files) addDictFiles(e.target.files);
                e.target.value = "";
              }}
              className="hidden"
            />
          </div>

          {/* Pre-flight summary — what we're about to import.
              Shows the view label (Databases / Tables / Columns / …)
              instead of the raw filename, the file size in human-
              friendly units, and an estimated row count produced
              client-side by sampling each file's head. The estimate
              is shown as "≈ 9.8M" so users don't mistake it for a
              hard count — the server reports the exact number after
              the parse phase. */}
          {dictFiles.length > 0 && (() => {
            const totalBytes = dictFiles.reduce((s, f) => s + f.size, 0);
            const estimatedTotalRows = dictFiles.reduce((s, f) => {
              const est = dictPreflight.get(`${f.name}::${f.size}`);
              return s + (est?.estimatedRows ?? 0);
            }, 0);
            return (
              <div className="mt-3 bg-gray-50 border border-gray-200 rounded-lg overflow-hidden">
                <div className="px-3 py-1.5 bg-gray-100 border-b border-gray-200 text-[11px] text-td-gray-dark flex items-center justify-between">
                  <span>
                    {dictFiles.length} file{dictFiles.length === 1 ? "" : "s"} ready —{" "}
                    <strong>{formatBytes(totalBytes)}</strong>
                    {estimatedTotalRows > 0 && (
                      <>
                        {" · ≈ "}
                        <strong>{formatRowCount(estimatedTotalRows)}</strong>
                        {" rows"}
                      </>
                    )}
                  </span>
                  <button
                    onClick={() => {
                      setDictFiles([]);
                      setDictPreflight(new Map());
                    }}
                    className="text-blue-600 hover:underline text-[11px]"
                  >
                    Clear all
                  </button>
                </div>
                <ul className="divide-y divide-gray-100">
                  {dictFiles.map((f, i) => {
                    const est = dictPreflight.get(`${f.name}::${f.size}`);
                    const label = viewLabelForFile(f.name);
                    return (
                      <li
                        key={`${f.name}-${i}`}
                        className="px-3 py-1.5 flex items-center gap-2 text-[11px]"
                      >
                        <FileText size={11} className="text-gray-400 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-td-navy truncate">
                              {label ?? f.name}
                            </span>
                            {label && (
                              <span className="text-[10px] text-gray-400 font-mono truncate">
                                {f.name}
                              </span>
                            )}
                          </div>
                        </div>
                        <span className="text-[10px] text-gray-500 whitespace-nowrap font-mono">
                          {formatBytes(f.size)}
                        </span>
                        <span
                          className="text-[10px] text-gray-500 whitespace-nowrap font-mono w-16 text-right"
                          title={
                            est?.estimatedRows != null
                              ? `Estimated from a ${formatBytes(est.sampleBytesUsed)} sample`
                              : "Not estimated client-side (counted server-side)"
                          }
                        >
                          {est === undefined
                            ? "…"
                            : est.estimatedRows != null
                              ? `≈ ${formatRowCount(est.estimatedRows)}`
                              : "—"}
                        </span>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            removeDictFile(i);
                          }}
                          className="text-gray-400 hover:text-red-500"
                          aria-label={`Remove ${f.name}`}
                        >
                          <X size={11} />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })()}

          {/* Coverage hint with estimated row counts per view.
              The COVERAGE block is the user's "what am I about to import"
              snapshot — it answers "do I have all 6 views" AND "how
              much data is in each one" at a glance. The estimates
              come from the same pre-flight pass that fills the file
              list above; we just look up the matched file by prefix. */}
          {dictFiles.length > 0 && (() => {
            // For each expected view, find the dropped file (if any)
            // and its pre-flight estimate. Built as a flat array so
            // the JSX below stays linear.
            const coverageWithRows = dictCoverage.map((c) => {
              const file = dictFiles.find((f) =>
                f.name.toLowerCase().startsWith(c.prefix),
              );
              const est = file
                ? dictPreflight.get(`${file.name}::${file.size}`)
                : undefined;
              return {
                ...c,
                fileSize: file?.size ?? null,
                estimatedRows: est?.estimatedRows ?? null,
                estimatePending: c.matched && est === undefined,
              };
            });
            return (
              <div className="mt-3">
                <div className="text-[10px] font-semibold text-td-gray-dark uppercase tracking-wider mb-1.5">
                  Coverage: {dictMatchedCount} of {DICT_EXPECTED.length} views
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-3 gap-y-1.5 text-[11px]">
                  {coverageWithRows.map((c) => (
                    <div
                      key={c.prefix}
                      className={`flex items-center gap-1.5 ${
                        c.matched ? "text-emerald-700" : "text-gray-400"
                      }`}
                    >
                      {c.matched ? (
                        <CheckCircle2 size={10} className="shrink-0" />
                      ) : (
                        <span className="w-2 h-2 rounded-full border border-gray-300 shrink-0" />
                      )}
                      <span className="truncate">{c.label}</span>
                      {c.matched && (
                        <span className="ml-auto text-[10px] font-mono text-gray-500 whitespace-nowrap">
                          {c.estimatePending
                            ? "…"
                            : c.estimatedRows != null
                              ? `≈ ${formatRowCount(c.estimatedRows)} rows`
                              : c.fileSize != null
                                ? formatBytes(c.fileSize)
                                : ""}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}

          {/* Upload button + result */}
          {!dictResult && (
            <>
              <div className="mt-4 flex items-center gap-3">
                <button
                  onClick={handleDictUpload}
                  disabled={dictFiles.length === 0 || dictUploading}
                  className="flex items-center gap-2 bg-blue-500 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                >
                  <Upload size={14} />
                  {dictUploading
                    ? dictPhase === "processing"
                      ? "Processing on server…"
                      : "Uploading…"
                    : "Upload batch"}
                </button>
                {/* Cancel button: visible only while an import is in
                    flight. Disabled (with a spinner-ish caption) once
                    the user has clicked it, so we don't fire multiple
                    cancel POSTs. The actual rollback happens at the
                    next persist heartbeat (~6 s) — until then the
                    button stays in "Cancelling…" state. */}
                {dictUploading && dictActiveImportId != null && (
                  <button
                    onClick={handleDictCancel}
                    disabled={dictCancelling}
                    className="flex items-center gap-2 border border-red-300 text-red-700 hover:bg-red-50 px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    <X size={14} />
                    {dictCancelling ? "Cancelling…" : "Cancel"}
                  </button>
                )}
                {dictFiles.length > 0 && !dictUploading && (
                  <span className="text-[11px] text-td-gray-dark">
                    {(dictFiles.reduce((s, f) => s + f.size, 0) / 1024 / 1024).toFixed(1)} MB across{" "}
                    {dictFiles.length} file{dictFiles.length === 1 ? "" : "s"}
                  </span>
                )}
              </div>

              {/* Per-step checklist driven by the server-side progress
                  poller. While the body is going up the wire, the
                  upload step renders live bytes-on-the-wire %. After
                  the server picks it up, every other step (parse,
                  validate, persist, post-ingest) appears with its
                  own status + caption + sub-progress where available. */}
              <DictImportProgress
                phase={dictPhase}
                loaded={dictUploadedBytes}
                total={dictTotalBytes}
                uploadingStartedAt={dictPhaseStartedAt}
                serverState={dictServerProgress}
              />
            </>
          )}

          {/* Success card */}
          {dictResult && (
            <div
              className={`mt-4 rounded-lg p-4 border ${
                dictResult.skipped_existing
                  ? "bg-amber-50 border-amber-200"
                  : "bg-emerald-50 border-emerald-200"
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <CheckCircle2
                  size={14}
                  className={dictResult.skipped_existing ? "text-amber-600" : "text-emerald-600"}
                />
                <div className="text-sm font-semibold text-td-navy">
                  {dictResult.skipped_existing
                    ? `Idempotent — snapshot #${dictResult.snapshot_id} already existed`
                    : `Snapshot #${dictResult.snapshot_id} created`}
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
                <SummaryStat label="Source" value={dictResult.source_system_name} />
                <SummaryStat
                  label="Run ID"
                  value={dictResult.extract_run_id.slice(0, 16) + "…"}
                />
                <SummaryStat label="Schemas" value={String(dictResult.schemas_created)} />
                <SummaryStat label="Tables" value={String(dictResult.tables_created)} />
                <SummaryStat label="Columns" value={String(dictResult.columns_created)} />
                <SummaryStat label="Indices" value={String(dictResult.indices_seen)} />
                <SummaryStat
                  label="Partitioning"
                  value={String(dictResult.partitioning_seen)}
                />
                <SummaryStat
                  label="DDL fragments"
                  value={String(dictResult.tabletext_seen)}
                />
              </div>
              <button
                onClick={clearDictImport}
                className="mt-3 text-xs text-blue-600 hover:underline"
              >
                Done — close panel
              </button>
            </div>
          )}

          {/* Error card — server batch-validator emits multi-line diffs;
              preserve newlines and use mono so the user can see exactly
              which file disagreed with which. */}
          {dictError && (
            <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3">
              <div className="flex items-start gap-2 mb-1">
                <AlertCircle size={12} className="text-red-600 mt-0.5 shrink-0" />
                <div className="text-xs font-semibold text-red-900">Upload rejected</div>
              </div>
              <pre className="text-[10px] text-red-900 whitespace-pre-wrap font-mono leading-relaxed pl-5">
                {dictError}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* ──── Parser import panel ────
          Shown whenever the user has picked a file. Walks through three
          visual states: loading the dry-run → report + Confirm button →
          error. The raw JSON isn't dumped anymore; we show the backend's
          IngestionReport (input → filtered → would-persist + warnings). */}
      {(importFile || importError) && (
        <div className="bg-white rounded-xl shadow-sm border-2 border-td-orange p-5 mb-6">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <FileJson size={20} className="text-td-orange" />
              <h3 className="text-sm font-semibold text-td-navy">
                Parser JSON Import {importReport?.dry_run ? "— Preview (dry run)" : ""}
              </h3>
            </div>
            <button onClick={clearImport} className="text-td-gray-dark hover:text-td-navy">
              <X size={16} />
            </button>
          </div>

          {importFile && (
            <div className="text-xs text-td-gray-dark mb-3">
              <span className="font-medium">File:</span> {importFile.name} ({(importFile.size / 1024).toFixed(1)} KB)
              {importReport && (
                <>
                  <span className="mx-2 text-gray-400">•</span>
                  <span className="font-medium">Parse run:</span>{" "}
                  <code className="font-mono text-[10px]">{importReport.parse_run_id}</code>
                </>
              )}
            </div>
          )}

          {importing && !importReport && (
            <div className="text-xs text-td-gray-dark py-4">Running dry-run analysis…</div>
          )}

          {importReport && (
            <>
              {/* ──── Counts grid: input → filtered → would-persist ──── */}
              <div className="grid grid-cols-3 gap-3 mb-4">
                <CountsCard title="Input" counts={importReport.input_counts} tone="neutral" />
                <CountsCard title="Filtered out" counts={importReport.filtered_counts} tone="warn" />
                <CountsCard
                  title={importReport.dry_run ? "Would persist" : "Persisted"}
                  counts={importReport.persisted_counts}
                  tone="ok"
                />
              </div>

              {/* ──── Structural-incompleteness indicator ────
                  The backend emits warnings mentioning "UNKNOWN" when the
                  parser payload is missing datasetType/dataType. Surfacing
                  this up-front is the main reason we built the dry-run flow
                  (so users don't persist incomplete snapshots by mistake). */}
              {importReport.warnings.some((w) => w.includes("UNKNOWN")) && (
                <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg p-3 mb-3">
                  <AlertCircle size={14} className="text-amber-600 shrink-0 mt-0.5" />
                  <div className="text-xs text-amber-900">
                    <strong>Structural snapshot incomplete</strong> — waiting for parser v2.
                    Some datasets/columns have no type information and will be stored
                    as <code className="font-mono">UNKNOWN</code>. Structural change detection
                    will be limited on those objects until Rahul&apos;s team ships the
                    additional fields.
                  </div>
                </div>
              )}

              {importReport.warnings.length > 0 && (
                <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 mb-3">
                  <div className="text-[11px] font-semibold text-td-navy mb-1.5">
                    Warnings ({importReport.warnings.length})
                  </div>
                  <ul className="space-y-1">
                    {importReport.warnings.map((w, i) => (
                      <li key={i} className="text-[11px] text-td-gray-dark flex gap-1.5">
                        <span className="text-amber-600">•</span>
                        <span>{w}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {importReport.dry_run && (
                <div className="flex items-center gap-3">
                  <button
                    onClick={handleConfirmImport}
                    disabled={confirming}
                    className="flex items-center gap-2 bg-td-orange text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-td-orange/90 disabled:opacity-50 transition-colors"
                  >
                    <Upload size={14} />
                    {confirming ? "Importing…" : "Confirm Import"}
                  </button>
                  <button
                    onClick={clearImport}
                    disabled={confirming}
                    className="px-3 py-2 text-xs text-td-gray-dark hover:text-td-navy disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <span className="text-[10px] text-td-gray-dark">
                    Creates a new snapshot from this parser feed.
                  </span>
                </div>
              )}
            </>
          )}

          {importError && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700 mt-3">
              {importError}
            </div>
          )}
        </div>
      )}

      {createError && <ErrorAlert message={createError} />}
      {error && <ErrorAlert message="Failed to load snapshots" />}
      {isLoading && <LoadingSpinner />}
      {data && data.snapshots.length === 0 && (
        <EmptyState message="No snapshots yet. Create one to get started." />
      )}

      {data && data.snapshots.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-td-navy text-white text-left">
                <th className="px-4 py-3 font-medium">ID</th>
                <th className="px-4 py-3 font-medium">Created</th>
                <th className="px-4 py-3 font-medium">Source</th>
                <th className="px-4 py-3 font-medium">Description</th>
                <th className="px-4 py-3 font-medium">Active</th>
                <th className="px-4 py-3 font-medium w-16">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(() => {
                // Only the highest-ID (latest) snapshot is deletable. Deleting
                // an older one would break diffs and impact results that
                // reference it — the backend also enforces this, the UI just
                // hides the button so users don't get a rejection error.
                const latestId = Math.max(...data.snapshots.map((s) => Number(s.snapshot_id)));
                return data.snapshots.map((s) => {
                  const id = Number(s.snapshot_id);
                  const isActive = activeSnapshotId === id;
                  const isLatest = id === latestId;
                  return (
                    <tr
                      key={s.snapshot_id}
                      onClick={() => setActiveSnapshotId(id)}
                      className={`border-t border-gray-100 cursor-pointer transition-colors ${
                        isActive ? "bg-blue-50" : "hover:bg-gray-50"
                      }`}
                    >
                      <td className="px-4 py-3 font-mono">{s.snapshot_id}</td>
                      <td className="px-4 py-3 text-td-gray-dark">
                        {new Date(s.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3">{s.source_system}</td>
                      <td className="px-4 py-3 text-td-gray-dark">
                        {s.description || "—"}
                      </td>
                      <td className="px-4 py-3">
                        {isActive && (
                          <Check size={16} className="text-td-object" />
                        )}
                      </td>
                      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                        {isLatest ? (
                          <button
                            onClick={() => setDeleteTarget(id)}
                            className="flex items-center gap-1 text-red-600 hover:bg-red-50 px-2 py-1 rounded text-xs transition-colors"
                            title="Delete this snapshot (latest only)"
                          >
                            <Trash2 size={12} />
                            Delete
                          </button>
                        ) : (
                          <span title="Only the latest snapshot can be deleted — protects data integrity">
                            <ShieldCheck size={14} className="text-td-gray-dark/40" />
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                });
              })()}
            </tbody>
          </table>
        </div>
      )}

      {/* ──── Delete confirmation modal ──── Click-outside cancels (unless
          a delete is in flight), inner clicks stopPropagation so they don't
          dismiss the modal. Button enabled only when confirmText === id. */}
      {deleteTarget !== null && (
        <div
          className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4"
          onClick={() => { if (!deleting) { setDeleteTarget(null); setConfirmText(""); } }}
        >
          <div
            className="bg-white rounded-2xl shadow-2xl border border-red-200 w-full max-w-md overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="bg-red-50 border-b border-red-200 px-5 py-4 flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center">
                <AlertTriangle size={20} className="text-red-600" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-red-900">Delete Snapshot #{deleteTarget}?</h3>
                <p className="text-[11px] text-red-700 mt-0.5">This action cannot be undone.</p>
              </div>
            </div>

            <div className="p-5 space-y-3">
              <p className="text-sm text-gray-700 leading-relaxed">
                You are about to permanently delete snapshot <strong className="font-mono">#{deleteTarget}</strong> and all its dependent data:
              </p>
              <ul className="text-xs text-td-gray-dark space-y-1 bg-gray-50 rounded-lg p-3 border border-gray-200">
                <li>• All databases, tables, and columns captured in this snapshot</li>
                <li>• All change events and diffs involving this snapshot</li>
                <li>• All graph nodes, edges, and impact analyses</li>
                <li>• All TAISA reasoning results tied to its changes</li>
              </ul>

              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-start gap-2">
                <ShieldCheck size={14} className="text-amber-600 shrink-0 mt-0.5" />
                <p className="text-xs text-amber-900">
                  <strong>Protection:</strong> Only the latest snapshot can be deleted. This safeguard prevents corrupting the diff/impact history.
                </p>
              </div>

              <div>
                <label className="text-xs font-medium text-td-navy block mb-1">
                  To confirm, type the snapshot ID: <code className="bg-gray-100 px-1.5 py-0.5 rounded font-mono">{deleteTarget}</code>
                </label>
                <input
                  type="text"
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  placeholder={`Type "${deleteTarget}" here`}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                  autoFocus
                />
              </div>
            </div>

            <div className="px-5 py-3 bg-gray-50 border-t border-gray-200 flex justify-end gap-2">
              <button
                onClick={() => { setDeleteTarget(null); setConfirmText(""); }}
                disabled={deleting}
                className="px-4 py-2 rounded-lg text-sm font-medium text-td-gray-dark hover:bg-gray-200 disabled:opacity-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting || confirmText !== String(deleteTarget)}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold bg-red-600 text-white hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <Trash2 size={14} />
                {deleting ? "Deleting..." : "Yes, delete permanently"}
              </button>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
}

// ──── CountsCard ────
// Renders one column of the three-up grid (input/filtered/persisted). Keys
// are dynamic because the backend dicts evolve independently of the UI —
// whatever the parser/ingestor adds shows up automatically.
function CountsCard({
  title,
  counts,
  tone,
}: {
  title: string;
  counts: Record<string, number>;
  tone: "neutral" | "warn" | "ok";
}) {
  const toneClasses = {
    neutral: "border-gray-200 bg-gray-50",
    warn: "border-amber-200 bg-amber-50/50",
    ok: "border-emerald-200 bg-emerald-50/50",
  }[tone];
  const titleClasses = {
    neutral: "text-td-gray-dark",
    warn: "text-amber-800",
    ok: "text-emerald-800",
  }[tone];

  const entries = Object.entries(counts);
  return (
    <div className={`rounded-lg border p-3 ${toneClasses}`}>
      <div className={`text-[10px] uppercase tracking-wide font-semibold mb-2 ${titleClasses}`}>
        {title}
      </div>
      {entries.length === 0 ? (
        <div className="text-[11px] text-td-gray-dark italic">—</div>
      ) : (
        <ul className="space-y-1">
          {entries.map(([k, v]) => (
            <li key={k} className="flex justify-between text-[11px]">
              <span className="text-td-gray-dark">{k.replace(/_/g, " ")}</span>
              <span className="font-mono font-semibold text-td-navy">{v}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ShareFileRow — one row in the share scan panel showing category + filenames.
function ShareFileRow({
  icon,
  label,
  files,
}: {
  icon: React.ReactNode;
  label: string;
  files: string[];
}) {
  return (
    <div className="flex items-start gap-2 text-[11px]">
      <span className={`mt-0.5 shrink-0 ${files.length > 0 ? "text-emerald-600" : "text-gray-300"}`}>
        {icon}
      </span>
      <div className="flex-1 min-w-0">
        <span className={`font-medium ${files.length > 0 ? "text-td-navy" : "text-gray-400"}`}>
          {label}
        </span>
        {files.length > 0 ? (
          <div className="text-[10px] text-td-gray-dark mt-0.5">
            {files.length} file{files.length !== 1 ? "s" : ""}:{" "}
            {files.slice(0, 3).join(", ")}
            {files.length > 3 ? ` +${files.length - 3} more` : ""}
          </div>
        ) : (
          <div className="text-[10px] text-gray-400 mt-0.5">No files found</div>
        )}
      </div>
    </div>
  );
}

// SummaryStat — used by the dict-import success card. Kept inline
// (instead of importing from a shared file) because it's a 4-line
// component used only on this page; the indirection cost outweighs
// the reuse benefit until a third caller appears.
function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white/60 rounded p-2 border border-white/40">
      <div className="text-[9px] text-td-gray-dark uppercase tracking-wider">{label}</div>
      <div className="text-xs font-bold text-td-navy mt-0.5 font-mono truncate">{value}</div>
    </div>
  );
}
