"use client";

import { useState } from "react";
import { mutate } from "swr";
import PageShell from "@/components/layout/PageShell";
import KpiCard from "@/components/shared/KpiCard";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { useSelection } from "@/lib/SelectionContext";
import { runDiff } from "@/lib/api/diff";
import { getDiffDetails } from "@/lib/api/diff";
import type { DiffDetailResponse, DiffDetailItem } from "@/lib/api/types";
import {
  Play,
  Check,
  AlertTriangle,
  ShieldAlert,
  ChevronDown,
  ChevronRight,
  Code,
  Copy,
  CheckCheck,
  Loader2,
} from "lucide-react";
import { getDDL } from "@/lib/api/ddl";
import type { DDLResponse, DDLItem } from "@/lib/api/types";
import { useToast } from "@/components/shared/ToastProvider";
import SchemaVisualDiff from "@/components/shared/SchemaVisualDiff";
import { LayoutList, GitCompare, TrendingUp, Clock, Target, Flame, ExternalLink, BarChart3, ArrowRight } from "lucide-react";
import Link from "next/link";
import { changeTypeLabel } from "@/lib/terminology";
import { GuidedSection } from "@/components/shared/GuidedSection";

const SEVERITY_STYLES: Record<string, string> = {
  HIGH: "bg-red-100 text-red-800",
  MEDIUM: "bg-orange-100 text-orange-800",
  LOW: "bg-green-100 text-green-800",
};

function SeverityBadge({ severity }: { severity: string | null }) {
  const sev = severity ?? "LOW";
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${SEVERITY_STYLES[sev] ?? SEVERITY_STYLES.LOW}`}
    >
      {sev}
    </span>
  );
}

function BreakingBadge({ breaking }: { breaking: boolean | null }) {
  if (!breaking) return null;
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-600 text-white">
      <ShieldAlert size={10} />
      BREAKING
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-td-navy text-white hover:bg-td-navy-light transition-colors"
    >
      {copied ? <CheckCheck size={12} /> : <Copy size={12} />}
      {copied ? "Copied!" : "Copy SQL"}
    </button>
  );
}

// ──── ExpandableRow ────
// Each change row can expand to reveal before/after JSON, quick-link chips to
// related views (lineage/timeline/impact/usage), and — if the user has clicked
// "Generate DDL" — the suggested SQL statement with TAISA warnings.
// Local `open` state per row keeps this independent from the selection set.
function ExpandableRow({
  item,
  ddlItem,
  selected,
  onToggle,
}: {
  item: DiffDetailItem;
  ddlItem?: DDLItem;
  selected: boolean;
  onToggle: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <tr
        className="border-t border-gray-100 hover:bg-gray-50 cursor-pointer"
        onClick={() => setOpen(!open)}
      >
        {/* stopPropagation: the <tr> click toggles the expand panel — we don't
            want ticking the checkbox to also open/close the row. */}
        <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggle(item.change_id)}
            className="w-3.5 h-3.5 rounded border-gray-300 text-td-navy accent-td-navy cursor-pointer"
          />
        </td>
        <td className="px-4 py-3">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </td>
        <td className="px-4 py-3 font-mono text-xs">{item.change_id}</td>
        <td className="px-4 py-3 text-xs text-td-gray-dark">
          #{item.snapshot_from} → #{item.snapshot_to}
        </td>
        <td className="px-4 py-3">
          <span className="bg-td-navy/10 text-td-navy px-2 py-0.5 rounded text-xs font-medium">
            {item.object_type}
          </span>
        </td>
        <td className="px-4 py-3 font-mono text-xs">
          {item.object_identifier}
        </td>
        <td className="px-4 py-3">
          <span
            className="bg-td-orange/10 text-td-orange px-2 py-0.5 rounded text-xs font-medium"
            title={item.change_type}
          >
            {changeTypeLabel(item.change_type)}
          </span>
        </td>
        <td className="px-4 py-3">
          <SeverityBadge severity={item.severity} />
        </td>
        <td className="px-4 py-3">
          <BreakingBadge breaking={item.is_breaking} />
        </td>
      </tr>
      {open && (
        <tr className="bg-gray-50">
          <td colSpan={9} className="px-8 py-3">
            {/* Quick Links — navigate to related views filtered by this object */}
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <span className="text-[10px] font-semibold text-td-gray-dark uppercase tracking-wider">Explore this object:</span>
              <Link
                href={`/lineage?object=${encodeURIComponent(item.object_identifier)}&snapshot=${item.snapshot_to}`}
                className="flex items-center gap-1 bg-white border border-gray-200 text-td-navy px-2.5 py-1 rounded-full text-[11px] font-medium hover:bg-td-navy hover:text-white hover:border-td-navy transition-colors"
                title="View data lineage for this object"
              >
                <TrendingUp size={11} />
                Lineage
                <ExternalLink size={9} className="opacity-60" />
              </Link>
              <Link
                href={`/timeline?object=${encodeURIComponent(item.object_identifier)}`}
                className="flex items-center gap-1 bg-white border border-gray-200 text-td-navy px-2.5 py-1 rounded-full text-[11px] font-medium hover:bg-td-navy hover:text-white hover:border-td-navy transition-colors"
                title="See the change history of this object across snapshots"
              >
                <Clock size={11} />
                Timeline
                <ExternalLink size={9} className="opacity-60" />
              </Link>
              <Link
                href={`/impact/${item.change_id}`}
                className="flex items-center gap-1 bg-white border border-gray-200 text-td-navy px-2.5 py-1 rounded-full text-[11px] font-medium hover:bg-td-navy hover:text-white hover:border-td-navy transition-colors"
                title="Detailed impact analysis for this specific change"
              >
                <Target size={11} />
                Impact detail
                <ExternalLink size={9} className="opacity-60" />
              </Link>
              <Link
                href={`/usage?object=${encodeURIComponent(item.object_identifier)}`}
                className="flex items-center gap-1 bg-white border border-gray-200 text-td-navy px-2.5 py-1 rounded-full text-[11px] font-medium hover:bg-td-navy hover:text-white hover:border-td-navy transition-colors"
                title="See how much this object is used"
              >
                <Flame size={11} />
                Usage
                <ExternalLink size={9} className="opacity-60" />
              </Link>
            </div>

            <div className="grid grid-cols-2 gap-4 text-xs">
              <div>
                <span className="font-semibold text-td-upstream block mb-1">
                  Before State
                </span>
                <pre className="bg-white rounded p-2 border border-gray-200 overflow-auto max-h-32">
                  {item.before_state
                    ? JSON.stringify(item.before_state, null, 2)
                    : "null (new object)"}
                </pre>
              </div>
              <div>
                <span className="font-semibold text-td-downstream block mb-1">
                  After State
                </span>
                <pre className="bg-white rounded p-2 border border-gray-200 overflow-auto max-h-32">
                  {item.after_state
                    ? JSON.stringify(item.after_state, null, 2)
                    : "null (removed)"}
                </pre>
              </div>
            </div>
            {/* DDL Panel */}
            {ddlItem && (
              <div className="mt-3 pt-3 border-t border-gray-200">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Code size={14} className="text-td-navy" />
                    <span className="font-semibold text-td-navy text-xs">Suggested DDL</span>
                  </div>
                  <CopyButton text={ddlItem.ddl_combined} />
                </div>
                <pre className="bg-slate-900 text-green-400 rounded p-3 overflow-auto max-h-40 text-xs font-mono">
                  {ddlItem.ddl_combined}
                </pre>
                {ddlItem.taisa_warnings.length > 0 && (
                  <div className="mt-2 bg-orange-50 border border-orange-200 rounded p-2">
                    <div className="flex items-center gap-1 text-orange-700 text-xs font-semibold mb-1">
                      <AlertTriangle size={12} />
                      TAISA Risk Warnings
                    </div>
                    <ul className="text-xs text-orange-800 space-y-0.5">
                      {ddlItem.taisa_warnings.map((w, i) => (
                        <li key={i}>- {w}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export default function ChangesPage() {
  const { data: snapData } = useSnapshots();
  // SelectionContext survives client-side navigation, so a diff run here stays
  // loaded when the user comes back from /impact, /lineage, etc.
  const {
    activeChangeId, setActiveChangeId, setActiveDiffPair,
    setCachedDiffDetails, cachedDiffDetails,
  } = useSelection();

  // Diff runner form state
  const [diffFrom, setDiffFrom] = useState("");
  const [diffTo, setDiffTo] = useState("");
  const [running, setRunning] = useState(false);
  const [diffMsg, setDiffMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Two-tier cache: prefer context (shared across pages), fall back to local
  // state if the user re-runs a diff here without going through context first.
  const [localDetails, setLocalDetails] = useState<DiffDetailResponse | null>(null);
  const details = cachedDiffDetails ?? localDetails;

  // Filter + view-mode state — purely presentational, doesn't hit the API.
  const [filterSeverity, setFilterSeverity] = useState<string>("ALL");
  const [filterBreaking, setFilterBreaking] = useState<string>("ALL");
  // Object filter: free-text, case-insensitive substring match against
  // `object_identifier`. Empty string = show all. Kept as plain state
  // (no debounce) because the changes list is bounded (tens-hundreds of
  // rows) and re-filtering on every keystroke is imperceptible.
  const [filterObject, setFilterObject] = useState<string>("");
  // DDL generation is a separate backend call, triggered by the "Generate DDL"
  // button. We keep the response here rather than in context because it's
  // specific to this page and can be heavy (SQL blobs).
  const [ddlData, setDdlData] = useState<DDLResponse | null>(null);
  const [ddlLoading, setDdlLoading] = useState(false);
  // selectedChangeIds drives BOTH the DDL filter (generate SQL for a subset)
  // and the "select all" checkbox in the table header.
  const [selectedChangeIds, setSelectedChangeIds] = useState<Set<number>>(new Set());
  const [viewMode, setViewMode] = useState<"table" | "visual">("table");

  const { toast } = useToast();
  const snapshots = snapData?.snapshots ?? [];

  function toggleChangeSelection(id: number) {
    setSelectedChangeIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Note: toggleAllChanges uses filteredChanges defined below — safe because
  // it's only called from an event handler, not during render.
  function toggleAllChanges() {
    setSelectedChangeIds((prev) => {
      const q = filterObject.trim().toLowerCase();
      const allIds = (details?.changes ?? [])
        .filter((c) => {
          if (filterSeverity !== "ALL" && c.severity !== filterSeverity) return false;
          if (filterBreaking === "BREAKING" && !c.is_breaking) return false;
          if (filterBreaking === "NON_BREAKING" && c.is_breaking) return false;
          if (q && !c.object_identifier.toLowerCase().includes(q)) return false;
          return true;
        })
        .map((c) => c.change_id);
      if (prev.size === allIds.length && allIds.every((id) => prev.has(id))) {
        return new Set();
      }
      return new Set(allIds);
    });
  }

  // Run Diff = POST /diff/run (expensive, writes new change rows on the backend).
  // View Existing = GET /diff/details (cheap, reads pre-computed changes).
  // We separate the two so users don't silently re-run a heavy job when they
  // only want to inspect.
  async function handleRunDiff() {
    if (!diffFrom || !diffTo) return;
    setRunning(true);
    setDiffMsg(null);
    setError(null);
    try {
      const res = await runDiff({
        snapshot_from: diffFrom,
        snapshot_to: diffTo,
      });
      setDiffMsg(`Detected ${res.changes_detected} new change(s)`);
      // Revalidate the global "changes" SWR key so dashboards update.
      await mutate("changes");
      // Auto-load details so the user doesn't have to click again.
      await loadDetails(Number(diffFrom), Number(diffTo));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Diff failed";
      setDiffMsg(msg);
    } finally {
      setRunning(false);
    }
  }

  async function loadDetails(from: number, to: number) {
    setLoading(true);
    setError(null);
    try {
      const data = await getDiffDetails(from, to);
      // Write to BOTH local state and context: local for the current render,
      // context so Impact/Lineage/Simulation can pick up the same diff without
      // the user selecting snapshots again.
      setLocalDetails(data);
      setCachedDiffDetails(data);
      setActiveDiffPair({ snapshotFrom: from, snapshotTo: to });
      toast(`Diff loaded: ${data.summary.total} change(s), ${data.summary.breaking_count} breaking`, data.summary.breaking_count > 0 ? "error" : "success");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load diff details");
    } finally {
      setLoading(false);
    }
  }

  async function handleLoadExisting() {
    if (!diffFrom || !diffTo) return;
    await loadDetails(Number(diffFrom), Number(diffTo));
  }

  async function handleGenerateDDL() {
    const f = details?.snapshot_from;
    const t = details?.snapshot_to;
    if (!f || !t) return;
    setDdlLoading(true);
    try {
      const data = await getDDL(f, t);
      setDdlData(data);
      toast(`DDL generated: ${data.total} statement(s)`, "success");
      // Scroll to DDL panel after a short delay
      setTimeout(() => {
        document.getElementById("ddl-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    } catch {
      // silently fail DDL generation
    } finally {
      setDdlLoading(false);
    }
  }

  // Lookup map so each ExpandableRow can render its DDL in O(1) instead of
  // scanning ddlData.items on every row render.
  const ddlMap = new Map<number, DDLItem>();
  if (ddlData) {
    for (const item of ddlData.items) {
      ddlMap.set(item.change_id, item);
    }
  }

  // DDL panel shows either the filtered selection or everything. An empty
  // selection means "show all" (matches the Generate DDL button behaviour).
  const ddlDisplayItems = ddlData
    ? selectedChangeIds.size > 0
      ? ddlData.items.filter((d) => selectedChangeIds.has(d.change_id))
      : ddlData.items
    : [];

  // Filter changes — severity + breaking + free-text object match.
  // `q` is pre-computed once outside the filter closure so it's not
  // re-lowercased on every row.
  const q = filterObject.trim().toLowerCase();
  const filteredChanges =
    details?.changes.filter((c) => {
      if (filterSeverity !== "ALL" && c.severity !== filterSeverity)
        return false;
      if (filterBreaking === "BREAKING" && !c.is_breaking) return false;
      if (filterBreaking === "NON_BREAKING" && c.is_breaking) return false;
      if (q && !c.object_identifier.toLowerCase().includes(q)) return false;
      return true;
    }) ?? [];

  return (
    <PageShell
      title="Changes"
      subtitle="Structural changes between snapshots"
    >
      {/* ──── Diff runner ──── Pick two snapshots and either compute a fresh
          diff or load one that was already computed. Kept outside the numbered
          Section flow because it's a control block, not a report section —
          numbered sections appear below, once a diff has been loaded. */}
      <div className="bg-blue-50/40 border border-blue-100 rounded-lg px-3 py-2 mb-3 flex items-start gap-2">
        <ShieldAlert size={12} className="text-blue-500 shrink-0 mt-0.5" />
        <p className="text-[11px] text-td-gray-dark leading-relaxed">
          Pick two snapshots, run the diff, and SCION enumerates every structural change between them —
          tables added/removed, columns moved/renamed/retyped, nullability changes. The summary KPIs,
          filter-driven drill-down table, DDL generator and visual side-by-side all live below once
          a diff is loaded.
        </p>
      </div>
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        <h3 className="text-sm font-semibold text-td-navy mb-3">
          Compare Snapshots
        </h3>
        <div className="flex items-end gap-3 flex-wrap">
          <div>
            <label className="text-xs text-td-gray-dark block mb-1">
              From
            </label>
            <select
              value={diffFrom}
              onChange={(e) => setDiffFrom(e.target.value)}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm"
            >
              <option value="">Select snapshot</option>
              {snapshots.map((s) => (
                <option key={s.snapshot_id} value={s.snapshot_id}>
                  #{s.snapshot_id} — {s.source_system}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-td-gray-dark block mb-1">To</label>
            <select
              value={diffTo}
              onChange={(e) => setDiffTo(e.target.value)}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm"
            >
              <option value="">Select snapshot</option>
              {snapshots.map((s) => (
                <option key={s.snapshot_id} value={s.snapshot_id}>
                  #{s.snapshot_id} — {s.source_system}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={handleRunDiff}
            disabled={running || !diffFrom || !diffTo || diffFrom === diffTo}
            className="flex items-center gap-2 bg-td-navy text-white px-4 py-1.5 rounded text-sm font-medium hover:bg-td-navy-light disabled:opacity-50 transition-colors"
          >
            <Play size={14} />
            {running ? "Running..." : "Run Diff"}
          </button>
          <button
            onClick={handleLoadExisting}
            disabled={loading || !diffFrom || !diffTo}
            className="flex items-center gap-2 bg-td-object text-white px-4 py-1.5 rounded text-sm font-medium hover:bg-td-object/90 disabled:opacity-50 transition-colors"
          >
            View Existing Diff
          </button>
          {diffMsg && (
            <span className="text-sm text-td-gray-dark">{diffMsg}</span>
          )}
        </div>
      </div>

      {error && <ErrorAlert message={error} />}
      {loading && <LoadingSpinner />}

      {/* ──── Results section (only when `details` is loaded) ────
          Shows summary KPIs, severity/breaking explainer, view-mode toggle,
          filters, the changes table with inline DDL, and a drill-down hint. */}
      {/* ──── Results section (only when `details` is loaded) ──── */}
      {details && (
        <>
          {/* ═══════════════════════════════════════════════════════════
              SECTION 1 · Summary
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="1. Summary"
            subtitle="What came back from the diff, at a glance"
            icon={BarChart3}
            intro={
              <>
                <strong>Severity</strong> (High / Medium / Low) measures the <em>technical risk</em>
                of a change. <strong>Breaking</strong> is an independent flag: it means the change
                breaks backward compatibility with downstream consumers (a dropped column referenced
                by a view, a DECIMAL(10,2) → VARCHAR type change). These dimensions are separate —
                a change can be <strong>BREAKING with MEDIUM severity</strong>, or HIGH severity but
                non-breaking. The cards below count each bucket.
              </>
            }
          >
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
              <KpiCard label="Total Changes" value={details.summary.total} color="#00233C" />
              <KpiCard label="Breaking" value={details.summary.breaking_count} color="#DC2626" />
              <KpiCard label="High Severity" value={details.summary.high_count} color="#DC2626" />
              <KpiCard label="Medium Severity" value={details.summary.medium_count} color="#F59E0B" />
              <KpiCard label="Low Severity" value={details.summary.low_count} color="#16A34A" />
            </div>
          </GuidedSection>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 2 · Detailed changes (view + filters + table/visual)
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="2. Detailed changes"
            subtitle="Row-level drill-down with filters, DDL generation, and visual diff"
            icon={LayoutList}
            intro={
              <>
                <strong>Table view</strong> gives you one row per change with filters (by severity
                or breaking-only) and checkbox selection to generate suggested DDL for just the
                rows you care about. <strong>Visual diff</strong> renders the snapshot schemas
                side-by-side so you can see added, removed, and modified columns in their structural
                context. Click any row to expand its before/after JSON and quick-links to lineage,
                timeline, impact, or usage.
              </>
            }
          >
          {/* View mode toggle — Table mode is the default; Visual mode renders
              a side-by-side SchemaVisualDiff component, which has its own data
              requirements and hides the filter bar. */}
          <div className="flex items-center gap-2 mb-4">
            <button
              onClick={() => setViewMode("table")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                viewMode === "table" ? "bg-td-navy text-white" : "bg-gray-100 text-td-gray-dark hover:bg-gray-200"
              }`}
            >
              <LayoutList size={13} />
              Table View
            </button>
            <button
              onClick={() => setViewMode("visual")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                viewMode === "visual" ? "bg-td-navy text-white" : "bg-gray-100 text-td-gray-dark hover:bg-gray-200"
              }`}
            >
              <GitCompare size={13} />
              Visual Diff
            </button>
          </div>

          {/* Visual Diff mode */}
          {viewMode === "visual" && details && (
            <div className="mb-6">
              <SchemaVisualDiff snapshotFrom={details.snapshot_from} snapshotTo={details.snapshot_to} changes={details.changes} />
            </div>
          )}

          {/* Filters — only in table mode. Layout: an object-name search
              box on its own line (wider so long identifiers like
              `core_banking.transactions.amount` don't truncate), then the
              severity + breaking + actions row below. */}
          {viewMode === "table" && (
          <div className="flex flex-col gap-3 mb-4">
            <div className="flex items-center gap-2">
              <div className="relative flex-1 max-w-md">
                <svg
                  width="14" height="14"
                  viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  className="absolute left-2.5 top-1/2 -translate-y-1/2 text-td-gray-dark"
                ><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                <input
                  type="text"
                  value={filterObject}
                  onChange={(e) => setFilterObject(e.target.value)}
                  placeholder="Filter by object name (e.g. core_banking.transactions)"
                  className="w-full border border-gray-300 rounded pl-8 pr-8 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-td-navy/30 focus:border-td-navy"
                />
                {filterObject && (
                  <button
                    onClick={() => setFilterObject("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-td-gray-dark hover:text-td-navy"
                    title="Clear filter"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                  </button>
                )}
              </div>
              {filterObject && (
                <span className="text-[11px] text-td-gray-dark">
                  Match: <strong className="text-td-navy">{filteredChanges.length}</strong> of {details.changes.length}
                </span>
              )}
            </div>

            <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2 text-xs">
              <span className="text-td-gray-dark">Severity:</span>
              {["ALL", "HIGH", "MEDIUM", "LOW"].map((s) => (
                <button
                  key={s}
                  onClick={() => setFilterSeverity(s)}
                  className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
                    filterSeverity === s
                      ? "bg-td-navy text-white"
                      : "bg-gray-100 text-td-gray-dark hover:bg-gray-200"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-td-gray-dark">Breaking:</span>
              {["ALL", "BREAKING", "NON_BREAKING"].map((b) => (
                <button
                  key={b}
                  onClick={() => setFilterBreaking(b)}
                  className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
                    filterBreaking === b
                      ? "bg-td-navy text-white"
                      : "bg-gray-100 text-td-gray-dark hover:bg-gray-200"
                  }`}
                >
                  {b.replace("_", " ")}
                </button>
              ))}
            </div>
            <span className="text-xs text-td-gray-dark ml-auto">
              Showing {filteredChanges.length} of {details.changes.length}{" "}
              changes
              {selectedChangeIds.size > 0 && (
                <span className="ml-2 text-td-orange font-medium">
                  ({selectedChangeIds.size} selected for DDL)
                </span>
              )}
            </span>
            <button
              onClick={handleGenerateDDL}
              disabled={ddlLoading}
              className="flex items-center gap-2 bg-slate-800 text-green-400 px-3 py-1.5 rounded text-xs font-medium hover:bg-slate-700 disabled:opacity-50 transition-colors"
            >
              {ddlLoading ? <Loader2 size={12} className="animate-spin" /> : <Code size={12} />}
              {ddlLoading
                ? "Generating..."
                : ddlData
                  ? "Regenerate DDL"
                  : selectedChangeIds.size > 0
                    ? `Generate DDL (${selectedChangeIds.size})`
                    : "Generate DDL (All)"}
            </button>
            {details && (
              <a
                href={`${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1"}/export/changes/${details.snapshot_from}/${details.snapshot_to}`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 bg-green-600 text-white px-3 py-1.5 rounded text-xs font-medium hover:bg-green-700 transition-colors"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
                Export CSV
              </a>
            )}
            </div>
          </div>
          )}

          {/* ──── Changes table + DDL panel ──── Each row is expandable.
              Selection checkboxes drive which changes are sent to Generate DDL. */}
          {viewMode === "table" && (<>
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-td-navy text-white text-left">
                  {/* "Select all" — checked only when every currently-visible
                      (i.e. filtered) row is selected. Comparing just sizes is
                      not enough because hidden rows may be selected from a
                      previous filter state. */}
                  <th className="px-4 py-3 w-8">
                    <input
                      type="checkbox"
                      checked={filteredChanges.length > 0 && selectedChangeIds.size === filteredChanges.length && filteredChanges.every((c) => selectedChangeIds.has(c.change_id))}
                      onChange={toggleAllChanges}
                      className="w-3.5 h-3.5 rounded cursor-pointer accent-td-orange"
                    />
                  </th>
                  <th className="px-4 py-3 w-8"></th>
                  <th className="px-4 py-3 font-medium">ID</th>
                  <th className="px-4 py-3 font-medium">Snapshot</th>
                  <th className="px-4 py-3 font-medium">Object Type</th>
                  <th className="px-4 py-3 font-medium">Object</th>
                  <th className="px-4 py-3 font-medium">Change</th>
                  <th className="px-4 py-3 font-medium">Severity</th>
                  <th className="px-4 py-3 font-medium">Breaking</th>
                </tr>
              </thead>
              <tbody>
                {filteredChanges.map((item) => (
                  <ExpandableRow
                    key={item.change_id}
                    item={item}
                    ddlItem={ddlMap.get(item.change_id)}
                    selected={selectedChangeIds.has(item.change_id)}
                    onToggle={toggleChangeSelection}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {/* DDL Panel — appears after Generate DDL */}
          {ddlData && ddlDisplayItems.length > 0 && (
            <div id="ddl-panel" className="mt-6 bg-slate-900 rounded-lg shadow-lg border border-slate-700 overflow-hidden">
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-3 bg-slate-800 border-b border-slate-700">
                <div className="flex items-center gap-2">
                  <Code size={16} className="text-green-400" />
                  <span className="text-sm font-bold text-green-400">
                    Generated DDL — {ddlDisplayItems.length} of {ddlData.total} statement(s)
                    {selectedChangeIds.size > 0 && (
                      <span className="text-slate-400 font-normal ml-1">(filtered)</span>
                    )}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <CopyButton
                    text={ddlDisplayItems.map((d) => `-- [${d.change_type}] ${d.object_identifier}\n${d.ddl_combined}`).join("\n\n")}
                  />
                  <button
                    onClick={() => setDdlData(null)}
                    className="text-slate-400 hover:text-white text-xs px-2 py-1 rounded hover:bg-slate-700 transition-colors"
                  >
                    Close
                  </button>
                </div>
              </div>
              {/* DDL statements */}
              <div className="divide-y divide-slate-700 max-h-[500px] overflow-y-auto">
                {ddlDisplayItems.map((item) => (
                  <div key={item.change_id} className="px-5 py-4">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-mono text-slate-400">#{item.change_id}</span>
                        <span className="text-xs text-green-400 font-medium">{item.object_identifier}</span>
                        <span
                          className="bg-orange-500/20 text-orange-400 px-2 py-0.5 rounded text-[10px] font-medium"
                          title={item.change_type}
                        >
                          {changeTypeLabel(item.change_type)}
                        </span>
                        {item.is_breaking && (
                          <span className="bg-red-500/20 text-red-400 px-2 py-0.5 rounded text-[10px] font-bold">
                            BREAKING
                          </span>
                        )}
                      </div>
                      <CopyButton text={item.ddl_combined} />
                    </div>
                    <pre className="text-green-300 text-xs font-mono whitespace-pre-wrap leading-relaxed">
{item.ddl_combined}
                    </pre>
                    {item.taisa_warnings.length > 0 && (
                      <div className="mt-2 bg-orange-500/10 border border-orange-500/30 rounded p-2">
                        <div className="flex items-center gap-1 text-orange-400 text-xs font-semibold mb-1">
                          <AlertTriangle size={11} />
                          TAISA Warnings
                        </div>
                        <ul className="text-xs text-orange-300 space-y-0.5">
                          {item.taisa_warnings.map((w, i) => (
                            <li key={i}>- {w}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          </>)}
          </GuidedSection>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 3 · Next steps
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="3. What next?"
            subtitle="Ship the changes you understand, dig deeper into the ones you don't"
            icon={ArrowRight}
            intro={
              <>
                The diff pair <strong>#{details.snapshot_from} → #{details.snapshot_to}</strong>{" "}
                is selected and shared across the app. Click over to <strong>Impact Analysis</strong>{" "}
                for the full propagation report, or summon <strong>TAISA</strong> (bottom-right)
                to reason over all {details.summary.total} changes at once. If only one change is
                weird, scope TAISA to it via the selector below.
              </>
            }
          >
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
              <div className="flex items-center gap-3">
                <Check size={16} className="text-td-downstream" />
                <span className="text-sm text-td-navy">
                  <strong>Diff #{details.snapshot_from} → #{details.snapshot_to}</strong> is the active pair.
                </span>
              </div>
              <details className="mt-3">
                <summary className="text-xs text-td-gray-dark cursor-pointer hover:text-td-navy">
                  Scope TAISA to a single change...
                </summary>
                <div className="mt-2">
                  <select
                    value={activeChangeId ?? ""}
                    onChange={(e) =>
                      setActiveChangeId(e.target.value ? Number(e.target.value) : null)
                    }
                    className="border border-gray-300 rounded px-3 py-1.5 text-sm min-w-[400px]"
                  >
                    <option value="">Select a change...</option>
                    {details.changes.map((c) => (
                      <option key={c.change_id} value={c.change_id}>
                        #{c.change_id} — {changeTypeLabel(c.change_type)}: {c.object_identifier} [{c.severity}]
                      </option>
                    ))}
                  </select>
                  {activeChangeId && (
                    <span className="ml-3 text-xs text-td-object">
                      <Check size={12} className="inline" /> Change #{activeChangeId} selected
                    </span>
                  )}
                </div>
              </details>
            </div>
          </GuidedSection>
        </>
      )}

      {!details && !loading && (
        <EmptyState message="Select two snapshots and run a diff to see changes." />
      )}
    </PageShell>
  );
}
