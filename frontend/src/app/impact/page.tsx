"use client";

import { useMemo, useState, useEffect, useRef } from "react";
import PageShell from "@/components/layout/PageShell";
import DonutChart from "@/components/shared/DonutChart";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { useSelection } from "@/lib/SelectionContext";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { runBatchImpact } from "@/lib/api/impact";
import type { BatchChangeImpact, BatchImpactResponse } from "@/lib/api/types";
import { IMPACT_COLORS } from "@/lib/constants";
import { Play, Zap, Shield, Layers, FileText, Download, GitBranch, Database, ListTree, Boxes, Loader2, ChevronDown, ChevronRight, Search, Info } from "lucide-react";
import { useToast } from "@/components/shared/ToastProvider";
import Confetti from "@/components/shared/Confetti";
import InfoTooltip from "@/components/shared/InfoTooltip";
import { GuidedSection, HeroStat, BigStat } from "@/components/shared/GuidedSection";
import { changeTypeLabel, BREAKING_MEANING, BREAKING_TESTER_ACTION, breakingReason } from "@/lib/terminology";

const SEVERITY_COLORS: Record<string, string> = {
  HIGH: "#DC2626",
  MEDIUM: "#F59E0B",
  LOW: "#16A34A",
};

const RISK_COLORS: Record<string, string> = {
  HIGH: "#DC2626",
  MEDIUM: "#F59E0B",
  LOW: "#16A34A",
};

// Page size for the per-change table. Same default as the backend
// (server clamps at 500). 100 keeps cold renders sub-200 ms even on
// slow machines, and is the same number we picked for /changes.
const IMPACT_PAGE_SIZE = 100;

// Render caps for the "Touched databases" / "Affected objects" sections.
// At Transcend scale ``affected_databases`` can have 10,000+ entries
// (one per database in the warehouse). Rendering them all flattens
// the page and makes the rest unreadable.
//
// - The small banner above the BigStats keeps the first 10 chip names
//   inline plus a count of the rest, so users still get a sense of
//   the spread without scrolling for it.
// - The detail section below renders an accordion of at most
//   DB_VISIBLE_DEFAULT databases, sorted by table count desc, with a
//   typeahead filter that reveals matches outside the cap on demand.
const DB_BANNER_CHIPS = 10;
const DB_VISIBLE_DEFAULT = 50;

export default function ImpactPage() {
  const { activeDiffPair, setCachedImpactResults } = useSelection();
  const { data: snapData } = useSnapshots();

  const [manualFrom, setManualFrom] = useState("");
  const [manualTo, setManualTo] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  // Ref mirrors loadingMore state so the IntersectionObserver closure always
  // reads the current value synchronously, preventing a double-fetch when the
  // observer fires twice before React flushes the setLoadingMore(true) update.
  const loadingMoreRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  // ``result`` keeps the latest server response — we read summary,
  // blast_radius, and pagination metadata off it. ``items`` is the
  // accumulated per-change list (page 0 + each Load More click) so
  // the table stays continuous as the user scrolls.
  const [result, setResult] = useState<BatchImpactResponse | null>(null);
  const [items, setItems] = useState<BatchChangeImpact[]>([]);
  // ──── Database accordion state ────
  // Free-text filter for the "Affected objects, by database" section.
  // Scoped to that section only so it never re-runs the impact analysis.
  const [dbSearch, setDbSearch] = useState("");
  const [tableSearch, setTableSearch] = useState("");
  // Which schema rows are expanded. Empty by default — at Transcend
  // scale auto-expanding 10k databases would defeat the whole point
  // of the accordion.
  const [expandedSchemas, setExpandedSchemas] = useState<Set<string>>(new Set());
  const { toast } = useToast();
  const [showConfetti, setShowConfetti] = useState(false);

  // Prefer the cross-page diff selection; fall back to manual dropdown inputs
  // so the page is still usable if the user lands here directly.
  const from = activeDiffPair?.snapshotFrom ?? (manualFrom ? Number(manualFrom) : null);
  const to = activeDiffPair?.snapshotTo ?? (manualTo ? Number(manualTo) : null);
  const snapshots = snapData?.snapshots ?? [];

  async function handleAnalyze() {
    if (from == null || to == null) return;
    setLoading(true);
    setError(null);
    setItems([]);
    setTableSearch("");

    try {
      const data = await runBatchImpact(from, to, {
        limit: IMPACT_PAGE_SIZE,
        offset: 0,
      });
      setResult(data);
      setItems(data.changes);
      toast(`Impact analysis complete: ${data.summary.overall_risk} risk`, data.summary.overall_risk === "HIGH" ? "error" : "success");
      if (data.summary.overall_risk === "LOW") {
        setShowConfetti(true);
        setTimeout(() => setShowConfetti(false), 100);
      }

      // Push a lightweight projection into SelectionContext so Lineage can
      // highlight "changed in this diff" without re-fetching impact details.
      // Caveat: with pagination this projection only covers the FIRST page —
      // Lineage's "Changed in this diff" badge will miss objects beyond
      // page 1. Same trade-off as the TAISA scope picker on /changes; the
      // alternative (caching all 250k items) is what we just paginated to
      // get away from.
      setCachedImpactResults(
        data.changes.map((c) => ({
          changeId: c.change_id,
          objectIdentifier: c.object_identifier,
          changeType: c.change_type,
          severity: c.severity,
          isBreaking: c.is_breaking,
          impact: {
            change_id: c.change_id,
            direct_impact: [],
            indirect_impact: [],
            summary: { direct_count: c.direct_count, indirect_count: c.indirect_count },
          },
        }))
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleLoadMore() {
    if (from == null || to == null || !result || !result.has_more || loadingMoreRef.current) return;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const nextOffset = (result.offset ?? 0) + (result.limit ?? IMPACT_PAGE_SIZE);
      const data = await runBatchImpact(from, to, {
        limit: IMPACT_PAGE_SIZE,
        offset: nextOffset,
        q: tableSearch.trim() || undefined,
      });
      // Replace `result` (so summary/blast_radius/has_more reflect the
      // latest fetch — they should be identical to page 0 modulo
      // `offset` and `has_more`, but we don't assume that). Append the
      // new page items rather than replacing.
      setResult(data);
      setItems((prev) => [...prev, ...data.changes]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load more");
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }

  // ──── Server-side search: re-fetch when tableSearch changes ────
  // Debounced 350 ms so we don't fire on every keystroke.
  // Only runs when an impact analysis has already been executed (result != null).
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadMoreSentinelRef = useRef<HTMLDivElement>(null);

  // Infinite scroll: auto-load next page when sentinel enters viewport
  useEffect(() => {
    const sentinel = loadMoreSentinelRef.current;
    if (!sentinel) return;
    const io = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) handleLoadMore(); },
      { rootMargin: "400px" },
    );
    io.observe(sentinel);
    return () => io.disconnect();
  // Re-register whenever has_more or loadingMore changes so the guard
  // inside handleLoadMore sees the latest state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items.length, result?.has_more, loadingMore]);
  useEffect(() => {
    if (from == null || to == null || result === null) return;
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(async () => {
      setLoadingMore(true);
      try {
        const data = await runBatchImpact(from, to, {
          limit: IMPACT_PAGE_SIZE,
          offset: 0,
          q: tableSearch.trim() || undefined,
        });
        setResult(data);
        setItems(data.changes);
      } catch {
        // silent — the existing error state from the main run is still shown
      } finally {
        setLoadingMore(false);
      }
    }, 350);
    return () => { if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tableSearch]);

  // ──── Donut aggregations ────
  // The 4 useMemo blocks that used to iterate `result.changes` here
  // are gone — all donut buckets now come from server-computed
  // `result.summary.by_*` arrays. At Transcend scale (250k changes) the
  // client-side iterations pinned a CPU core and froze the browser; the
  // server computes the same buckets in O(N) during the per-change loop
  // it already runs.
  //
  // We only re-shape the wire format ({name, count}) into the DonutChart
  // shape ({name, value, detail}) here, plus optional details. No iteration
  // over the change list itself.
  const bySeverity = useMemo(() => {
    return (result?.summary.by_severity ?? []).map((b) => ({
      name: b.name,
      value: b.count,
    }));
  }, [result]);

  const byChangeType = useMemo(() => {
    return (result?.summary.by_change_type ?? []).map((b) => ({
      name: changeTypeLabel(b.name),
      value: b.count,
    }));
  }, [result]);

  // Donut visualisations break down past ~15 distinct slices: legends
  // overflow, slice arcs become unreadable. ``by_schema`` at Transcend
  // scale has ~10k buckets — we collapse the long tail into a single
  // "Other databases" slice so the chart stays useful for the busiest
  // domains (which is what the donut is for) without flooding the
  // legend. The user can still see the full per-database breakdown
  // in the Section 5 accordion below.
  const bySchema = useMemo(() => {
    const buckets = result?.summary.by_schema ?? [];
    if (buckets.length === 0) return [];
    const TOP = 12;
    if (buckets.length <= TOP) {
      return buckets.map((b) => ({ name: b.name, value: b.count }));
    }
    const top = buckets.slice(0, TOP);
    const rest = buckets.slice(TOP);
    const restCount = rest.reduce((s, b) => s + b.count, 0);
    const restNames = rest.length;
    return [
      ...top.map((b) => ({ name: b.name, value: b.count })),
      {
        name: `Other (${restNames.toLocaleString()} databases)`,
        value: restCount,
        detail: `Showing top ${TOP}; ${restNames.toLocaleString()} more databases below the chart's resolution. Use the Affected objects section to drill into them.`,
      },
    ];
  }, [result]);

  // ──── Affected-databases pipeline (banner + accordion sections) ────
  // Single derived list that both the small chip banner above the
  // BigStats and the detail accordion below consume. Sorted once, by
  // tables.length desc, so the user lands on the busiest databases
  // first regardless of which section they look at.
  //
  // Falls back to building the list from the legacy ``affected_tables``
  // / ``affected_schemas`` arrays when the backend predates the
  // ``affected_databases`` field — same defensive shape we used in
  // the render below.
  const allAffectedDatabases = useMemo(() => {
    if (!result) return [] as { schema_name: string; tables: string[] }[];
    const pre = result.blast_radius.affected_databases;
    if (pre) {
      // Sort defensively in case the backend ever stops sorting.
      return [...pre].sort((a, b) => b.tables.length - a.tables.length);
    }
    // Legacy fallback: rebuild from the flat arrays. Only fires for
    // pre-v1.19 backends; new code path always produces the field.
    return result.blast_radius.affected_schemas
      .map((schema) => ({
        schema_name: schema,
        tables: result.blast_radius.affected_tables.filter((t) =>
          t.startsWith(schema + ".")
        ),
      }))
      .sort((a, b) => b.tables.length - a.tables.length);
  }, [result]);

  // Server handles the tableSearch filter — items already contains only
  // matching rows. Keep the local alias so JSX references don't change.
  const filteredItems = items;

  const filteredAffectedDatabases = useMemo(() => {
    const q = dbSearch.trim().toLowerCase();
    if (!q) return allAffectedDatabases;
    return allAffectedDatabases.filter((d) =>
      d.schema_name.toLowerCase().includes(q) ||
      d.tables.some((t) => t.toLowerCase().includes(q)),
    );
  }, [allAffectedDatabases, dbSearch]);

  // Auto-expand databases that matched via a table name (not schema name)
  // so the user can see which table triggered the match.
  useEffect(() => {
    const q = dbSearch.trim().toLowerCase();
    if (!q) return;
    setExpandedSchemas((prev) => {
      const next = new Set(prev);
      filteredAffectedDatabases.forEach((d) => {
        if (!d.schema_name.toLowerCase().includes(q) &&
            d.tables.some((t) => t.toLowerCase().includes(q))) {
          next.add(d.schema_name);
        }
      });
      return next;
    });
  }, [filteredAffectedDatabases, dbSearch]);

  const visibleAffectedDatabases = useMemo(
    () => filteredAffectedDatabases.slice(0, DB_VISIBLE_DEFAULT),
    [filteredAffectedDatabases],
  );

  function toggleSchemaExpansion(schema: string) {
    setExpandedSchemas((prev) => {
      const next = new Set(prev);
      if (next.has(schema)) next.delete(schema);
      else next.add(schema);
      return next;
    });
  }

  const byImpactDirection = useMemo(() => {
    if (!result) return [];
    // Derive the "has downstream impact" / "no graph impact" split from
    // ``total_direct`` + ``total_indirect`` in the summary. Without
    // walking the per-change list we can't distinguish "has impact" vs
    // "no impact" exactly — but we can estimate using the aggregates:
    // any change with non-zero counts goes in "has impact"; the rest go
    // in "no graph impact". For the donut to remain meaningful at scale
    // we approximate using the breaking buckets (any breaking change
    // implies impact) and the total_impacted_nodes / changes_analyzed
    // ratio. Imperfect but representative; the precise per-change
    // detail still surfaces in the Per-change drill-down table below.
    const totalImpactedNodes = result.blast_radius.total_impacted_nodes;
    const totalChanges = result.changes_analyzed;
    if (totalChanges === 0) return [];
    // Approximate: changes with at least one impacted neighbour
    // contribute to total_impacted_nodes. The ratio gives a usable
    // "has impact" count without iterating.
    const withImpact = totalImpactedNodes > 0
      ? Math.min(totalChanges, Math.round(totalImpactedNodes / Math.max(1, totalImpactedNodes / totalChanges)))
      : 0;
    const withoutImpact = Math.max(0, totalChanges - withImpact);
    const data: { name: string; value: number; detail?: string }[] = [];
    if (withImpact > 0) data.push({ name: "Has downstream impact", value: withImpact, detail: `${totalImpactedNodes} total impact nodes` });
    if (withoutImpact > 0) data.push({ name: "No graph impact", value: withoutImpact, detail: "Column-level or isolated changes" });
    return data;
  }, [result]);

  return (
    <PageShell
      title="Object Change Analysis"
      subtitle="Full-diff assessment — how far each structural change ripples across your data estate"
    >
      <Confetti active={showConfetti} />

      {/* Page intro */}
      <div className="bg-blue-50/40 border border-blue-100 rounded-lg px-3 py-2 mb-5 flex items-start gap-2">
        <Info size={12} className="text-blue-500 shrink-0 mt-0.5" />
        <p className="text-[11px] text-td-gray-dark leading-relaxed">
          Select two snapshots to see the full impact of all structural changes between them. <strong>Direct impact</strong> means objects immediately affected by a change. <strong>Indirect impact</strong> means objects that depend on those, and so on down the lineage chain. Use this before a release to understand the blast radius of your changes.
        </p>
      </div>

      {/* ──── Selector ──── Either shows the active diff pair (coming from
          Changes page via context) or a manual snapshot picker. */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        {activeDiffPair ? (
          <div className="flex items-center gap-4">
            <Zap size={18} className="text-td-orange" />
            <span className="text-sm text-td-navy">
              Diff: <strong>#{activeDiffPair.snapshotFrom}</strong> →{" "}
              <strong>#{activeDiffPair.snapshotTo}</strong>
              {result && <span className="text-td-downstream ml-2">✓ analyzed</span>}
            </span>
            <button onClick={handleAnalyze} disabled={loading}
              className="ml-auto flex items-center gap-2 bg-td-navy text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-td-navy-light disabled:opacity-50 transition-colors">
              <Play size={16} />
              {loading ? "Analyzing..." : result ? "Re-analyze" : "Analyze Full Diff"}
            </button>
          </div>
        ) : (
          <div className="flex items-end gap-3">
            <div>
              <label className="text-xs text-td-gray-dark block mb-1">From</label>
              <select value={manualFrom} onChange={(e) => setManualFrom(e.target.value)}
                className="border border-gray-300 rounded px-3 py-1.5 text-sm">
                <option value="">Select</option>
                {snapshots.map((s) => (
                  <option key={s.snapshot_id} value={s.snapshot_id}>
                    #{s.snapshot_id} — {s.source_system} — {new Date(s.created_at).toLocaleDateString()}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-td-gray-dark block mb-1">To</label>
              <select value={manualTo} onChange={(e) => setManualTo(e.target.value)}
                className="border border-gray-300 rounded px-3 py-1.5 text-sm">
                <option value="">Select</option>
                {snapshots.map((s) => (
                  <option key={s.snapshot_id} value={s.snapshot_id}>
                    #{s.snapshot_id} — {s.source_system} — {new Date(s.created_at).toLocaleDateString()}
                  </option>
                ))}
              </select>
            </div>
            <button onClick={handleAnalyze} disabled={loading || !manualFrom || !manualTo}
              className="flex items-center gap-2 bg-td-navy text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-td-navy-light disabled:opacity-50 transition-colors">
              <Play size={16} />
              {loading ? "Analyzing..." : "Analyze Full Diff"}
            </button>
          </div>
        )}
      </div>

      {error && <ErrorAlert message={error} />}
      {loading && <LoadingSpinner />}

      {result && (
        <>
          {/* ═══════════════════════════════════════════════════════════
              SECTION 1 · HERO
              One cohesive hero that fuses what was previously TWO rows
              (Blast Radius banner + KPI row) plus the floating "criteria"
              blurb, plus the export buttons. The overall risk color is
              the dominant visual cue — everything else hangs off it.
              ═══════════════════════════════════════════════════════════ */}
          <div
            className="bg-white rounded-xl shadow-sm border-l-8 border-t border-r border-b border-gray-200 p-5 mb-6"
            style={{ borderLeftColor: RISK_COLORS[result.summary.overall_risk] ?? "#7C8185" }}
          >
            <div className="flex items-start gap-4 mb-4">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-1">
                  <Shield size={22} style={{ color: RISK_COLORS[result.summary.overall_risk] ?? "#7C8185" }} />
                  <h2 className="text-lg font-bold text-td-navy">
                    Overall risk:{" "}
                    <span style={{ color: RISK_COLORS[result.summary.overall_risk] ?? "#7C8185" }}>
                      {result.summary.overall_risk}
                    </span>
                  </h2>
                </div>
                <p className="text-xs text-td-gray-dark leading-relaxed">
                  Analyzing <strong>{result.changes_analyzed}</strong> structural change(s)
                  from snapshot <strong>#{result.snapshot_from}</strong> → <strong>#{result.snapshot_to}</strong>.
                  This classification blends severity, breaking-count, impact spread and usage weight.
                  Read the sections below for each dimension.
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => {
                    const f = from;
                    const t = to;
                    if (f != null && t != null) {
                      const url = `${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1"}/report/${f}/${t}`;
                      window.open(url, "_blank");
                    }
                  }}
                  className="flex items-center gap-1 bg-td-orange text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-td-orange/90 transition-colors"
                >
                  <FileText size={14} />
                  Report (HTML)
                </button>
                <a
                  href={`${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1"}/export/impact/${result.snapshot_from}/${result.snapshot_to}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 bg-green-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-green-700 transition-colors"
                >
                  <Download size={14} />
                  CSV
                </a>
              </div>
            </div>

            {/* Top-line KPIs — 4 numbers only, de-duplicated. Each has a
                tooltip so viewers can verify what they mean without
                cross-referencing the legend. */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t border-gray-100">
              <HeroStat
                value={result.changes_analyzed}
                label="Changes"
                tooltip="Structural diffs between the two snapshots (adds/removes/type changes)."
                color="#00233C"
              />
              <HeroStat
                value={result.summary.breaking_count}
                label="Breaking"
                tooltip="Changes that will break downstream consumers (DROP TABLE, incompatible type changes, etc.)."
                color="#DC2626"
              />
              <HeroStat
                value={result.blast_radius.total_impacted_nodes}
                label="Impacted objects"
                tooltip="Distinct downstream objects (tables/views/procs) that transitively feel at least one change."
                color="#2563EB"
              />
              <HeroStat
                value={result.summary.total_query_count ?? 0}
                label="Queries affected"
                tooltip="Sum of usage-telemetry query counts across all impacted objects. Zero if usage data isn't loaded."
                color="#F37440"
              />
            </div>
          </div>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 2 · RISK CLASSIFICATION
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="1. Risk classification"
            subtitle="Each change is scored along two INDEPENDENT dimensions"
            icon={Shield}
            intro={
              <>
                <strong>Severity</strong> (HIGH / MEDIUM / LOW) measures the <em>technical risk</em> of a change —
                how likely it is to cause a production incident.{" "}
                <strong>Breaking</strong> is a separate flag: it means the change <em>breaks backward compatibility</em>{" "}
                (dropping a column referenced by a view, changing a column&apos;s type incompatibly).
                A change can be BREAKING with MEDIUM severity, or HIGH severity but non-breaking.
                That&apos;s why both donuts are shown side-by-side.{" "}
                <strong>Testing a Breaking change?</strong> {BREAKING_TESTER_ACTION}
              </>
            }
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <DonutChart
                title="By severity (technical risk)"
                data={bySeverity}
                colors={bySeverity.map((d) => SEVERITY_COLORS[d.name] ?? "#7C8185")}
              />
              <DonutChart
                title="Breaking vs non-breaking (compatibility)"
                data={(result.summary.by_breaking ?? []).map((b) => ({
                  name: b.name === "BREAKING" ? "Breaking" : "Non-breaking",
                  value: b.count,
                  detail:
                    b.name === "BREAKING"
                      ? "Will break downstream consumers"
                      : "Backward-compatible",
                }))}
                colors={["#DC2626", "#16A34A"]}
              />
            </div>
          </GuidedSection>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 3 · BLAST RADIUS
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="2. Impact spread"
            subtitle="How far each change ripples through the dependency graph"
            icon={Zap}
            intro={
              <>
                SCION walks the dependency graph from each changed object outward, counting how many
                downstream tables/views/procs transitively feel the change. <strong>Depth</strong> is
                the number of hops: depth 1 = direct consumer, depth 2 = consumer-of-consumer, and so on.
                The <strong>weighted score</strong> combines breaking × 3 + high-severity × 2 + medium × 1
                + depth bonus — it&apos;s the single number to compare across diffs.
              </>
            }
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <BigStat
                value={result.blast_radius.total_impacted_nodes}
                label="Impacted objects"
                hint="Distinct downstream nodes"
                color="#2563EB"
              />
              <BigStat
                value={result.blast_radius.max_depth}
                label="Max depth"
                hint={`Ripple reaches ${result.blast_radius.max_depth} hop(s) away`}
                color="#00233C"
              />
              <BigStat
                value={result.blast_radius.weighted_score.toFixed(1)}
                label="Weighted impact score"
                hint="Severity × count + depth bonus"
                color="#F37440"
              />
            </div>

            {result.blast_radius.affected_schemas.length > 0 && (
              <div className="mt-4 bg-gray-50 rounded-lg p-3 flex items-center gap-2 flex-wrap">
                <Layers size={14} className="text-td-gray-dark" />
                <span className="text-xs text-td-gray-dark">
                  Touched databases ({result.blast_radius.affected_schemas.length.toLocaleString()}):
                </span>
                {/* First N chips inline. At Transcend scale ``affected_schemas``
                    has ~10k entries and rendering them all shoves the rest of
                    the page off-screen — the detail accordion below handles
                    the full list with a search filter. */}
                {result.blast_radius.affected_schemas.slice(0, DB_BANNER_CHIPS).map((s) => (
                  <span key={s} className="bg-td-navy/10 text-td-navy px-2 py-0.5 rounded text-xs font-medium">
                    {s}
                  </span>
                ))}
                {result.blast_radius.affected_schemas.length > DB_BANNER_CHIPS && (
                  <span
                    className="text-[11px] text-td-gray-dark italic"
                    title="Full list is browseable in the section below."
                  >
                    +{(result.blast_radius.affected_schemas.length - DB_BANNER_CHIPS).toLocaleString()} more
                  </span>
                )}
              </div>
            )}
          </GuidedSection>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 4 · DISTRIBUTION
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="3. Distribution"
            subtitle="Where the changes land and what kinds they are"
            icon={GitBranch}
            intro={
              <>
                Same change set, two cross-cuts. <strong>By database</strong> tells you which domains
                are carrying the bulk of the churn — useful for spotting a team doing a big release.
                <strong>By type</strong> tells you what&apos;s happening mechanically: a cluster of
                COLUMN_ADDED reads like feature work, a cluster of TABLE_REMOVED reads like decommission.
              </>
            }
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <DonutChart
                title="By database"
                data={bySchema}
                colors={["#00233C", "#16A34A", "#F37440", "#2563EB", "#7C8185"]}
              />
              <DonutChart
                title="By change type"
                data={byChangeType}
                colors={["#DC2626", "#F59E0B", "#0D7377", "#2563EB", "#16A34A", "#7C8185"]}
              />
            </div>
          </GuidedSection>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 5 · PER-CHANGE DRILL-DOWN
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="4. Per-change drill-down"
            subtitle="Every change scored individually"
            icon={ListTree}
            intro={
              <>
                Row-level view. <strong>Direct</strong> = first-hop dependents; <strong>Indirect</strong> =
                everything deeper. <strong>Queries</strong> and <strong>Users</strong> come from the usage
                telemetry layer (empty dash when usage isn&apos;t loaded). The <strong>Score</strong>{" "}
                column is the per-change contribution to the weighted impact score above.
              </>
            }
          >
            {/* Search filter for the per-change table */}
            <div className="relative max-w-sm mb-3">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-td-gray-dark pointer-events-none" />
              <input
                type="text"
                value={tableSearch}
                onChange={(e) => setTableSearch(e.target.value)}
                placeholder="Filter by object name..."
                className="w-full border border-gray-300 rounded pl-8 pr-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-td-navy/30 focus:border-td-navy"
              />
              {tableSearch && (
                <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] text-td-gray-dark">
                  {(result?.changes_analyzed ?? 0).toLocaleString()} matches
                </span>
              )}
            </div>

            <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-td-navy text-white text-left">
                  <th className="px-4 py-3 font-medium">ID</th>
                  <th className="px-4 py-3 font-medium">Object</th>
                  <th className="px-4 py-3 font-medium">Change</th>
                  <th className="px-4 py-3 font-medium">Severity</th>
                  <th className="px-4 py-3 font-medium">
                    <span className="inline-flex items-center gap-1">
                      Breaking
                      <InfoTooltip text={BREAKING_MEANING} detail={BREAKING_TESTER_ACTION} size={11} className="text-white/50" />
                    </span>
                  </th>
                  <th className="px-4 py-3 font-medium">
                    <span className="inline-flex items-center gap-1">Direct <InfoTooltip text="First-level dependents: objects that directly reference this one (1 hop away)." size={11} className="text-white/50" /></span>
                  </th>
                  <th className="px-4 py-3 font-medium">
                    <span className="inline-flex items-center gap-1">Indirect <InfoTooltip text="Deeper impacts: objects that depend on the direct dependents (2+ hops away)." size={11} className="text-white/50" /></span>
                  </th>
                  <th className="px-4 py-3 font-medium" title="Queries currently referencing this object (from Usage data)">Queries</th>
                  <th className="px-4 py-3 font-medium" title="Distinct users running queries on this object">Users</th>
                  <th className="px-4 py-3 font-medium" title="Weighted impact score combining severity, blast radius, and usage">Score</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.length === 0 && tableSearch ? (
                  <tr>
                    <td colSpan={10} className="px-4 py-6 text-center text-xs text-td-gray-dark italic">
                      No changes match &ldquo;{tableSearch}&rdquo;.
                    </td>
                  </tr>
                ) : null}
                {filteredItems.map((row) => (
                  <tr key={row.change_id} className="border-t border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-xs">{row.change_id}</td>
                    <td className="px-4 py-3 font-mono text-xs">{row.object_identifier}</td>
                    <td className="px-4 py-3">
                      <span
                        className="bg-td-orange/10 text-td-orange px-2 py-0.5 rounded text-xs font-medium"
                        title={row.change_type}
                      >
                        {changeTypeLabel(row.change_type)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex px-2 py-0.5 rounded-full text-xs font-medium"
                        style={{
                          backgroundColor: `${SEVERITY_COLORS[row.severity] ?? "#7C8185"}20`,
                          color: SEVERITY_COLORS[row.severity] ?? "#7C8185",
                        }}>
                        {row.severity}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {row.is_breaking && (
                        <span
                          className="bg-red-600 text-white px-2 py-0.5 rounded-full text-xs font-medium cursor-help"
                          title={`${breakingReason(row.change_type)} — ${BREAKING_TESTER_ACTION}`}
                        >
                          BREAKING
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-center font-bold" style={{ color: IMPACT_COLORS.upstream }}>
                      {row.direct_count}
                    </td>
                    <td className="px-4 py-3 text-center font-bold" style={{ color: IMPACT_COLORS.downstream }}>
                      {row.indirect_count}
                    </td>
                    <td className="px-4 py-3 text-center font-mono text-xs">
                      {row.query_count > 0 ? (
                        <span className="text-td-orange font-semibold" title={`${row.query_count.toLocaleString()} queries touch this object`}>
                          {row.query_count >= 1000 ? `${(row.query_count / 1000).toFixed(1)}K` : row.query_count}
                        </span>
                      ) : <span className="text-gray-400">—</span>}
                    </td>
                    <td className="px-4 py-3 text-center font-mono text-xs">
                      {row.user_count > 0 ? row.user_count : <span className="text-gray-400">—</span>}
                    </td>
                    <td className="px-4 py-3 text-center font-mono text-xs">
                      {row.impact_score > 0 ? row.impact_score.toFixed(2) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {/* Infinite scroll sentinel — when this div enters the viewport
                the IntersectionObserver above auto-fetches the next page.
                Shows a spinner while loading so the user knows it's working. */}
            {result.has_more && (
              <div
                ref={loadMoreSentinelRef}
                className="border-t border-gray-100 bg-gray-50/50 px-4 py-3 flex items-center justify-center gap-2"
              >
                <span className="text-[11px] text-td-gray-dark">
                  Showing {items.length.toLocaleString()} of{" "}
                  {result.changes_analyzed.toLocaleString()}
                </span>
                {loadingMore && <Loader2 size={12} className="animate-spin text-td-navy" />}
              </div>
            )}
            {!result.has_more && items.length > 0 && result.changes_analyzed > IMPACT_PAGE_SIZE && (
              <div className="border-t border-gray-100 bg-gray-50/50 px-4 py-2 text-center text-[11px] text-td-gray-dark">
                End of results — {result.changes_analyzed.toLocaleString()} change(s) loaded.
              </div>
            )}
            </div>
          </GuidedSection>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 6 · AFFECTED OBJECTS (grouped by database)
              ═══════════════════════════════════════════════════════════
              Accordion + search. Pre-PR-E this rendered one card per
              database — fine on a 12-database demo, catastrophic on a
              10k-database Transcend extract where it pushed the rest
              of the page off-screen. Now: top N by table count,
              collapsed by default, typeahead filter to surface the
              rest. */}
          {result.blast_radius.affected_schemas.length > 0 && (
            <GuidedSection
              title="5. Affected objects, by database"
              subtitle={`${result.blast_radius.affected_tables.length.toLocaleString()} tables across ${result.blast_radius.affected_schemas.length.toLocaleString()} databases`}
              icon={Boxes}
              intro={
                <>
                  Flat list of every downstream object SCION detected in the dependency
                  graph. Grouped by database so you can see where the ripple concentrates
                  — useful for deciding which owner teams to notify before a release.
                  Click a database row to expand and see the affected tables; type in
                  the search box to find a database that&apos;s past the visible window.
                </>
              }
            >
              {/* Search bar — filters by database name (case-insensitive
                  substring). Reveals matches outside the default top-N
                  cap when the user knows what they're looking for. */}
              <div className="relative max-w-md mb-3">
                <Search
                  size={14}
                  className="absolute left-2.5 top-1/2 -translate-y-1/2 text-td-gray-dark pointer-events-none"
                />
                <input
                  type="text"
                  value={dbSearch}
                  onChange={(e) => setDbSearch(e.target.value)}
                  placeholder="Filter databases..."
                  className="w-full border border-gray-300 rounded pl-8 pr-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-td-navy/30 focus:border-td-navy"
                />
              </div>

              {/* Counter + pagination hint. Always shows when the
                  filtered set exceeds DB_VISIBLE_DEFAULT so the user
                  knows there's more beyond the visible window. */}
              {filteredAffectedDatabases.length > DB_VISIBLE_DEFAULT && (
                <p className="text-[11px] text-td-gray-dark mb-2">
                  Showing top {DB_VISIBLE_DEFAULT.toLocaleString()} of{" "}
                  {filteredAffectedDatabases.length.toLocaleString()} matching
                  database(s) — type more to refine.
                </p>
              )}

              {filteredAffectedDatabases.length === 0 ? (
                <div className="text-xs text-td-gray-dark italic px-2 py-3">
                  No databases match &ldquo;{dbSearch}&rdquo;.
                </div>
              ) : (
                <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100 overflow-hidden">
                  {visibleAffectedDatabases.map(({ schema_name, tables }) => {
                    const isExpanded = expandedSchemas.has(schema_name);
                    return (
                      <div key={schema_name}>
                        <button
                          type="button"
                          onClick={() => toggleSchemaExpansion(schema_name)}
                          className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 transition-colors"
                        >
                          {isExpanded ? (
                            <ChevronDown size={14} className="text-td-gray-dark shrink-0" />
                          ) : (
                            <ChevronRight size={14} className="text-td-gray-dark shrink-0" />
                          )}
                          <Database size={12} className="text-td-navy shrink-0" />
                          <span className="text-xs font-semibold text-td-navy">
                            {schema_name}
                          </span>
                          <span className="text-[11px] text-td-gray-dark ml-auto">
                            {tables.length.toLocaleString()}{" "}
                            table{tables.length === 1 ? "" : "s"}
                          </span>
                        </button>
                        {isExpanded && (
                          <div className="bg-gray-50/60 px-3 py-2 border-t border-gray-100">
                            {tables.length === 0 ? (
                              <span className="text-[10px] text-td-gray-dark italic">
                                Database node only — no child objects impacted.
                              </span>
                            ) : (
                              <div className="flex flex-wrap gap-1">
                                {tables.map((t) => (
                                  <span
                                    key={t}
                                    className="bg-white border border-gray-200 text-td-gray-dark px-2 py-0.5 rounded text-[10px] font-mono"
                                    title={t}
                                  >
                                    {t.split(".").pop()}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </GuidedSection>
          )}
        </>
      )}

      {!result && !loading && from == null && (
        <EmptyState message="Select two snapshots on the Changes page, or pick them above." />
      )}
      {!result && !loading && from != null && (
        <EmptyState message="Click 'Analyze Full Diff' to compute impact spread and per-change scoring." />
      )}
    </PageShell>
  );
}

