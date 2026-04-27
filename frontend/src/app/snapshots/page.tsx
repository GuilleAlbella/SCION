"use client";

import { useState, useRef } from "react";
import { mutate } from "swr";
import PageShell from "@/components/layout/PageShell";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { useSelection } from "@/lib/SelectionContext";
import { createSnapshot, deleteSnapshot } from "@/lib/api/snapshots";
import { previewParserImport, confirmParserImport } from "@/lib/api/parser_import";
import type { ParserImportResponse } from "@/lib/api/types";
import { Plus, Check, Upload, FileJson, X, Trash2, AlertTriangle, ShieldCheck, AlertCircle } from "lucide-react";
import { useToast } from "@/components/shared/ToastProvider";

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

  // Import state — hidden file input triggered by a button, then a preview
  // panel before the user confirms the actual import. The flow is two-phase:
  // (1) POST the raw JSON with dry_run=true to get an IngestionReport,
  // (2) show counts/warnings, then on "Confirm" POST again with dry_run=false.
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  // Raw parsed JSON kept so the confirm call can re-POST the same payload.
  const [importPayload, setImportPayload] = useState<unknown>(null);
  const [importReport, setImportReport] = useState<ParserImportResponse | null>(null);
  const [importing, setImporting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

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

  async function handleDelete() {
    if (deleteTarget == null) return;
    setDeleting(true);
    try {
      const res = await deleteSnapshot(deleteTarget);
      toast(
        `Snapshot #${res.deleted_snapshot_id} deleted. ${res.cascade.tables} tables, ${res.cascade.changes} changes removed.`,
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
          criticality) compares two snapshots to detect what moved. Create one via{" "}
          <strong>Capture Live Snapshot</strong> (reads the configured engine) or{" "}
          <strong>Import from Parser</strong> (ingests a DataDNA parser JSON feed —
          dictionary feed will plug in here in v1.10). Only the latest snapshot can
          be deleted; older ones are immutable to protect the diff history.
        </p>
      </div>

      {/* Action buttons */}
      <div className="flex gap-3 justify-end mb-4">
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
