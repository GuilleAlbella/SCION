"use client";

/**
 * /import — Data dictionary upload page.
 *
 * Surfaces the v1.12.00 backend pipeline (`POST /api/v1/dict-import`)
 * to end users. Drag-drop or click-to-pick the 6 .dat files Rahul's
 * extractor produces; we send them as one multipart batch and let the
 * server detect each file's content type by bytes + filename.
 *
 * Why a dedicated page instead of folding into Snapshots:
 *   - Snapshots is a read view. Imports change state — different mental
 *     model, different controls.
 *   - Helton/Pilar will be testing imports repeatedly during functional
 *     testing; deserves first-class navigation.
 *   - Future expansions (parser-import re-upload, usage-import when
 *     pipeline 3 lands) live naturally in one /import hub.
 *
 * Format-agnostic on the wire: today the user uploads `.dat`. Tomorrow,
 * if Rahul switches to JSON, the same UI works — content detection is
 * server-side.
 */

import { useState, useCallback, useRef, type DragEvent, type ChangeEvent } from "react";
import PageShell from "@/components/layout/PageShell";
import { GuidedSection } from "@/components/shared/GuidedSection";
import { importDictBatch, type DictImportResponse } from "@/lib/api/dict_import";
import { Upload, FileText, X, CheckCircle2, AlertCircle, Database, Layers, Inbox } from "lucide-react";

// The 6 dict views, with the filename prefix Rahul's extractor uses
// (mirrors `_DICT_FILENAME_PREFIXES` in the backend's format_detector).
// Showing this list explicitly lets the user verify they have a complete
// batch before clicking upload.
const EXPECTED_FILES = [
  { prefix: "databasesv_",                 label: "Databases (DBC.DatabasesV)" },
  { prefix: "tablesv_",                    label: "Tables / Views / Procs (DBC.TablesV)" },
  { prefix: "columnsv_",                   label: "Columns (DBC.ColumnsV)" },
  { prefix: "indicesv_",                   label: "Indices (DBC.IndicesV)" },
  { prefix: "partitioningconstraintsv_",   label: "Partitioning (DBC.PartitioningConstraintsV)" },
  { prefix: "tabletextv_",                 label: "DDL text (DBC.TableTextV)" },
];

export default function ImportPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<DictImportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // ──── File picking ────
  // Both drag-drop and the hidden <input> route through `addFiles` so
  // dedup + size limit + filename normalisation only need to live in
  // one place.
  const addFiles = useCallback((incoming: FileList | File[]) => {
    const arr = Array.from(incoming);
    setFiles((prev) => {
      // Dedupe by name+size — the same file dragged twice shouldn't
      // double up in the list. (Not by `File` identity because the
      // Browser File API gives a new object on each drag.)
      const key = (f: File) => `${f.name}::${f.size}`;
      const seen = new Set(prev.map(key));
      const merged = [...prev];
      for (const f of arr) {
        if (!seen.has(key(f))) merged.push(f);
      }
      return merged;
    });
    setResult(null);
    setError(null);
  }, []);

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files.length > 0) addFiles(e.dataTransfer.files);
  }
  function onPick(e: ChangeEvent<HTMLInputElement>) {
    if (e.target.files) addFiles(e.target.files);
    // Reset so picking the same file twice still re-fires onChange.
    e.target.value = "";
  }
  function removeFile(idx: number) {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  }

  // ──── Upload ────
  // The endpoint validates batch consistency server-side; we don't
  // pre-check on the client because the source-of-truth (record
  // contents) isn't worth duplicating reader logic in JS for.
  async function handleUpload() {
    if (files.length === 0) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const r = await importDictBatch(files);
      setResult(r);
      // On success, leave the file list visible so the user can see
      // what they uploaded; it'll get cleared on the next pick.
    } catch (e: unknown) {
      // Axios error: backend's HTTPException(detail=...) lands here as
      // `e.response.data.detail`. Surface verbatim — our backend writes
      // human-readable messages on purpose.
      let msg = "Upload failed.";
      if (typeof e === "object" && e !== null) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const ax = e as any;
        if (ax.response?.data?.detail) msg = String(ax.response.data.detail);
        else if (ax.message) msg = ax.message;
      }
      setError(msg);
    } finally {
      setUploading(false);
    }
  }

  // ──── Coverage check ────
  // For each expected file, mark whether the user has dropped one whose
  // filename starts with the right prefix. Pure presentation — the
  // backend doesn't require a complete batch (1 file is valid), this is
  // just a friendly "you forgot one" hint.
  const coverage = EXPECTED_FILES.map((spec) => ({
    ...spec,
    matched: files.some((f) => f.name.toLowerCase().startsWith(spec.prefix)),
  }));
  const matchedCount = coverage.filter((c) => c.matched).length;

  return (
    <PageShell title="Data Import" subtitle="Upload data dictionary or parser extracts">
      {/* ═══════════════════════════════════════════════════════════
          SECTION 1 · Upload
          ═══════════════════════════════════════════════════════════ */}
      <GuidedSection
        title="1. Upload data dictionary batch"
        subtitle="Drop the 6 files Rahul's extractor produced for one extraction run"
        icon={Upload}
        intro={
          <>
            Drop the <strong>6 .dat files</strong> from one extraction run
            (any order). SCION auto-detects each file&apos;s content from its
            bytes — filename helps but isn&apos;t required. All files must
            share the same <code className="font-mono">source_system_name</code> and{" "}
            <code className="font-mono">extract_run_id</code>; the server rejects
            mixed-batch uploads with a clear diff.
          </>
        }
      >
        {/* Drop zone + hidden input */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
            dragOver
              ? "border-blue-500 bg-blue-50"
              : "border-gray-300 hover:border-gray-400 bg-gray-50/40"
          }`}
        >
          <Inbox size={28} className={`mx-auto mb-2 ${dragOver ? "text-blue-500" : "text-gray-400"}`} />
          <p className="text-sm font-medium text-td-navy">
            {dragOver ? "Drop files here" : "Drop 1–6 .dat files here, or click to pick"}
          </p>
          <p className="text-[11px] text-td-gray-dark mt-1">
            Multipart upload — content-detection is server-side
          </p>
          <input
            ref={inputRef}
            type="file"
            multiple
            onChange={onPick}
            className="hidden"
            // Don't restrict by extension — a future JSON variant or
            // a renamed file should still be acceptable. The detector
            // decides.
          />
        </div>

        {/* Selected files list */}
        {files.length > 0 && (
          <div className="mt-4 bg-white border border-gray-200 rounded-lg overflow-hidden">
            <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 text-xs text-td-gray-dark flex items-center justify-between">
              <span>{files.length} file{files.length === 1 ? "" : "s"} ready to upload</span>
              <button
                onClick={() => setFiles([])}
                className="text-blue-600 hover:underline text-[11px]"
              >
                Clear all
              </button>
            </div>
            <ul className="divide-y divide-gray-100">
              {files.map((f, i) => (
                <li key={`${f.name}-${i}`} className="px-3 py-1.5 flex items-center gap-2 text-xs">
                  <FileText size={12} className="text-gray-400 shrink-0" />
                  <span className="font-mono truncate flex-1">{f.name}</span>
                  <span className="text-[10px] text-gray-400 whitespace-nowrap">
                    {(f.size / 1024).toFixed(1)} KB
                  </span>
                  <button
                    onClick={(e) => { e.stopPropagation(); removeFile(i); }}
                    className="text-gray-400 hover:text-red-500"
                    aria-label={`Remove ${f.name}`}
                  >
                    <X size={12} />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Coverage check — passive hint, doesn't block upload */}
        {files.length > 0 && (
          <div className="mt-4">
            <div className="text-[11px] font-semibold text-td-gray-dark uppercase tracking-wider mb-2">
              Coverage: {matchedCount} of {EXPECTED_FILES.length} dict views
            </div>
            <div className="grid grid-cols-2 gap-1.5 text-[11px]">
              {coverage.map((c) => (
                <div
                  key={c.prefix}
                  className={`flex items-center gap-1.5 ${c.matched ? "text-emerald-700" : "text-gray-400"}`}
                >
                  {c.matched
                    ? <CheckCircle2 size={11} className="shrink-0" />
                    : <span className="w-2.5 h-2.5 rounded-full border border-gray-300 shrink-0" />}
                  <span className="truncate">{c.label}</span>
                </div>
              ))}
            </div>
            {matchedCount < EXPECTED_FILES.length && (
              <p className="text-[10px] text-td-gray-dark mt-2 italic">
                Upload of partial batches is allowed — any missing view will simply have 0 records persisted.
              </p>
            )}
          </div>
        )}

        {/* Upload button */}
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={handleUpload}
            disabled={files.length === 0 || uploading}
            className="bg-td-orange text-white px-4 py-1.5 rounded text-sm font-medium hover:bg-orange-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {uploading ? "Uploading…" : "Upload batch"}
          </button>
          {files.length > 0 && (
            <span className="text-[11px] text-td-gray-dark">
              Total: {(files.reduce((s, f) => s + f.size, 0) / 1024).toFixed(1)} KB across {files.length} file{files.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
      </GuidedSection>

      {/* ═══════════════════════════════════════════════════════════
          SECTION 2 · Result
          ═══════════════════════════════════════════════════════════ */}
      {(result || error) && (
        <GuidedSection
          title="2. Result"
          subtitle={result ? "Snapshot persisted" : "Upload failed"}
          icon={result ? Layers : AlertCircle}
          intro={
            result ? (
              <>
                The batch was validated and persisted as snapshot{" "}
                <strong className="font-mono">#{result.snapshot_id}</strong>
                {result.skipped_existing && " (idempotent — same extract_run_id was already imported)"}.
                Counts below reflect what landed in the SCION database.
              </>
            ) : (
              <>The upload was rejected before any data was persisted. The error from the server is shown below verbatim.</>
            )
          }
        >
          {result && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <SummaryCard label="Snapshot" value={`#${result.snapshot_id}`} sub={result.skipped_existing ? "Already existed" : "Newly created"} />
              <SummaryCard label="Source" value={result.source_system_name} sub={result.extract_run_id.slice(0, 16) + "…"} />
              <SummaryCard label="Schemas" value={String(result.schemas_created)} sub="created" />
              <SummaryCard label="Tables" value={String(result.tables_created)} sub="created" />
              <SummaryCard label="Columns" value={String(result.columns_created)} sub="created" />
              <SummaryCard label="Indices" value={String(result.indices_seen)} sub="seen (not yet persisted)" />
              <SummaryCard label="Partitioning" value={String(result.partitioning_seen)} sub="seen (not yet persisted)" />
              <SummaryCard label="DDL fragments" value={String(result.tabletext_seen)} sub="seen (recoverable)" />
            </div>
          )}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <div className="flex items-start gap-2 mb-2">
                <AlertCircle size={14} className="text-red-600 mt-0.5 shrink-0" />
                <div className="text-sm font-semibold text-red-900">Upload rejected</div>
              </div>
              {/* Server messages can be multi-line (batch validator emits
                  a diff). Preserve newlines and use a mono font so the
                  error is easy to scan. */}
              <pre className="text-[11px] text-red-900 whitespace-pre-wrap font-mono leading-relaxed pl-5">
                {error}
              </pre>
            </div>
          )}
        </GuidedSection>
      )}

      {/* ═══════════════════════════════════════════════════════════
          SECTION 3 · Other ingest pipelines
          ═══════════════════════════════════════════════════════════ */}
      <GuidedSection
        title="3. Other ingest pipelines"
        subtitle="What else SCION accepts"
        icon={Database}
        intro={
          <>
            SCION accepts data from <strong>4 separate pipelines</strong>; this
            page covers Pipeline 2 (data dictionary). The others are listed
            here for context — see <code className="font-mono">docs/ingestion_pipelines.md</code> for the
            architecture decision behind keeping them separate.
          </>
        }
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px]">
          <PipelineCard
            num={1}
            title="Parser BTEQ/SQL"
            status="live"
            endpoint="POST /api/v1/parser-import"
            note="JSON parse-tree of CREATE / INSERT / view DDLs. UI: not yet wired here."
          />
          <PipelineCard
            num={2}
            title="Data dictionary"
            status="live"
            endpoint="POST /api/v1/dict-import"
            note="What this page uploads. 6 .dat files per extraction run."
          />
          <PipelineCard
            num={3}
            title="Usage statistics"
            status="planned"
            endpoint="(future)"
            note="DBQL / AMPUsage. Owner: Rahul. Format TBD; SCION never queries the customer DB directly."
          />
          <PipelineCard
            num={4}
            title="Raw code"
            status="planned"
            endpoint="(future)"
            note="BTEQ / proc bodies kept alongside the parsed tree, for code-diff UI and TAISA context."
          />
        </div>
      </GuidedSection>
    </PageShell>
  );
}

// ──── Local presentational components ────

function SummaryCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-3">
      <div className="text-[10px] text-td-gray-dark uppercase tracking-wider">{label}</div>
      <div className="text-lg font-bold text-td-navy mt-1 font-mono truncate">{value}</div>
      {sub && <div className="text-[10px] text-gray-400 mt-0.5 truncate">{sub}</div>}
    </div>
  );
}

function PipelineCard({
  num, title, status, endpoint, note,
}: {
  num: number;
  title: string;
  status: "live" | "planned";
  endpoint: string;
  note: string;
}) {
  return (
    <div className="border border-gray-200 rounded-lg p-3 bg-white">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[9px] font-bold text-td-gray-dark bg-gray-100 rounded px-1.5 py-0.5">
          PIPELINE {num}
        </span>
        <span
          className={`text-[9px] font-bold rounded px-1.5 py-0.5 ${
            status === "live"
              ? "bg-emerald-100 text-emerald-800"
              : "bg-gray-100 text-gray-500"
          }`}
        >
          {status.toUpperCase()}
        </span>
      </div>
      <div className="font-semibold text-sm text-td-navy">{title}</div>
      <div className="text-[10px] text-gray-400 font-mono mt-0.5">{endpoint}</div>
      <div className="text-[11px] text-td-gray-dark mt-1.5">{note}</div>
    </div>
  );
}
