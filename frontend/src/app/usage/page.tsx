"use client";

import { useState, useEffect, useMemo, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import PageShell from "@/components/layout/PageShell";
import KpiCard from "@/components/shared/KpiCard";
import DonutChart from "@/components/shared/DonutChart";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { useSelection } from "@/lib/SelectionContext";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { getUsageSummary, getCriticality, getObjectUsageDetail } from "@/lib/api/usage";
import type { ObjectUsageDetail } from "@/lib/api/usage";
import type { CriticalityResponse, UsageSummaryItem } from "@/lib/api/types";
import { Shield, Flame, Download, ListTree, GitBranch, X } from "lucide-react";
import RiskHeatmap from "@/components/shared/RiskHeatmap";
import InfoTooltip from "@/components/shared/InfoTooltip";
import { GuidedSection } from "@/components/shared/GuidedSection";

const CRIT_COLORS: Record<string, string> = {
  HIGH: "#DC2626",
  MEDIUM: "#F59E0B",
  LOW: "#16A34A",
};

function HeatBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  const color = pct > 60 ? "#DC2626" : pct > 30 ? "#F59E0B" : "#16A34A";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2.5 bg-gray-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-xs text-td-gray-dark w-12 text-right">{value.toLocaleString()}</span>
    </div>
  );
}

// Suspense wrapper required because UsagePage calls `useSearchParams` (for
// the ?object=X quick-link); Next.js 16 needs a boundary or the whole page
// is forced into client-rendering.
export default function UsagePageWrapper() {
  return (
    <Suspense fallback={<PageShell title="Usage & Criticality"><LoadingSpinner /></PageShell>}>
      <UsagePage />
    </Suspense>
  );
}

function UsagePage() {
  const { activeDiffPair } = useSelection();
  const { data: snapData } = useSnapshots();
  const snapshots = snapData?.snapshots ?? [];

  const [selectedSnap, setSelectedSnap] = useState<string>("");
  const [usage, setUsage] = useState<UsageSummaryItem[] | null>(null);
  const [criticality, setCriticality] = useState<CriticalityResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Deep-link support: e.g. /usage?object=dw.sales_fact from a Changes row
  // focuses that object in a dedicated drill-down card (and highlights it
  // in the tables below). The user can also click any table row to focus.
  const searchParams = useSearchParams();
  const router = useRouter();
  const focusedObject = searchParams.get("object");

  // Active drill-down object — seeded from the URL, updated when the user
  // clicks a row. The detail card + table highlight key off this.
  const [activeObject, setActiveObject] = useState<string | null>(focusedObject);
  const [detail, setDetail] = useState<ObjectUsageDetail | null>(null);
  useEffect(() => {
    setActiveObject(focusedObject);
  }, [focusedObject]);

  // Focus an object: update state + reflect in the URL (shallow replace,
  // no scroll jump) so the view is shareable and the back button works.
  const focusObject = useCallback(
    (name: string) => {
      setActiveObject(name);
      const params = new URLSearchParams(Array.from(searchParams.entries()));
      params.set("object", name);
      router.replace(`/usage?${params.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );

  const clearFocus = useCallback(() => {
    setActiveObject(null);
    setDetail(null);
    const params = new URLSearchParams(Array.from(searchParams.entries()));
    params.delete("object");
    const qs = params.toString();
    router.replace(qs ? `/usage?${qs}` : "/usage", { scroll: false });
  }, [router, searchParams]);

  // Columns (schema.table.column) don't carry their own usage/criticality
  // in SCION — those live at the table/object level — so resolve a column
  // to its parent table for the drill-down, mirroring the Lineage page.
  // `columnParent` keeps the original column name to explain the redirect.
  const { resolvedObject, columnParent } = useMemo(() => {
    if (!activeObject) return { resolvedObject: null as string | null, columnParent: null as string | null };
    const parts = activeObject.split(".");
    if (parts.length >= 3) {
      return { resolvedObject: parts.slice(0, 2).join("."), columnParent: activeObject };
    }
    return { resolvedObject: activeObject, columnParent: null };
  }, [activeObject]);

  // Fetch the per-object profile whenever the focused object or the
  // selected snapshot changes. Resolves ANY object via the backend, even
  // one outside the top-N usage / criticality rankings shown below.
  useEffect(() => {
    if (!resolvedObject || !selectedSnap) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    getObjectUsageDetail(Number(selectedSnap), resolvedObject)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [resolvedObject, selectedSnap]);

  // Usage summary is now snapshot-scoped (v1.13.04). When the user
  // selects a snapshot, we re-fetch usage filtered to objects that
  // exist in that snapshot's graph. Without a selection we don't fetch
  // — global aggregation is misleading because UsageEvent rows from
  // one source bleed across snapshots from a different source (e.g. a
  // dict-imported `Transcend-DevTest` snapshot would otherwise see
  // demo seed usage like `core_banking.transactions`).
  // Failures are swallowed because usage is optional — criticality
  // still works without it.
  useEffect(() => {
    if (!selectedSnap) {
      setUsage(null);
      return;
    }
    getUsageSummary(Number(selectedSnap))
      .then((d) => setUsage(d.items))
      .catch(() => {});
  }, [selectedSnap]);

  // Auto-seed criticality from an active diff, but ONLY if the user hasn't
  // already picked a snapshot manually — hence the `!selectedSnap` guard.
  // `selectedSnap` is deliberately omitted from deps to prevent re-seeding
  // after the user manually clears or changes it.
  useEffect(() => {
    if (activeDiffPair && !selectedSnap) {
      loadCriticality(String(activeDiffPair.snapshotTo));
    }
    // selectedSnap intentionally omitted — see comment above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeDiffPair]);

  async function loadCriticality(snapId: string) {
    setLoading(true);
    setError(null);
    setSelectedSnap(snapId);
    try {
      const data = await getCriticality(Number(snapId));
      setCriticality(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setLoading(false);
    }
  }

  const maxQueries = useMemo(
    () => Math.max(...(usage ?? []).map((u) => u.query_count), 1),
    [usage]
  );

  const critByLevel = useMemo(() => {
    if (!criticality) return [];
    return [
      { name: "HIGH", value: criticality.high_count },
      { name: "MEDIUM", value: criticality.medium_count },
      { name: "LOW", value: criticality.low_count },
    ].filter((d) => d.value > 0);
  }, [criticality]);

  // Detect whether the deep-linked object actually appears in any of the
  // data we'll render below. Two signals: usage heatmap hit, or criticality
  // table hit. If neither matches, the focus banner becomes informational
  // only ("no usage telemetry for this object") instead of claiming it's
  // been highlighted somewhere — which is the case for schema-level
  // objects that don't have query counts.
  const isFocused = useCallback(
    (name: string) =>
      !!activeObject && (activeObject === name || activeObject.endsWith("." + name)),
    [activeObject],
  );

  // Pretty-print the criticality level with its colour.
  const critColor = (lvl: string) => CRIT_COLORS[lvl] ?? "#7C8185";

  return (
    <PageShell title="Usage & Criticality" subtitle="Object usage frequency and business criticality">
      {/* Per-object drill-down card. Shown when an object is focused via
          the ?object= deep-link (from a Changes row) or by clicking a row
          in the tables below. Resolves ANY object, even one outside the
          top-N rankings, so "click transactions to see its insights"
          (Reunion 11) actually works on a real extract. */}
      {activeObject && (
        <div className="bg-white border-2 border-td-orange/40 rounded-lg p-4 mb-6 shadow-sm">
          <div className="flex items-start justify-between gap-3 mb-3">
            <div className="flex items-center gap-2 min-w-0">
              <Flame size={16} className="text-td-orange shrink-0" />
              <div className="min-w-0">
                <div className="text-[10px] uppercase tracking-wide text-td-gray-dark">Object drill-down</div>
                <div className="font-mono font-semibold text-td-navy text-sm truncate" title={resolvedObject ?? activeObject}>{resolvedObject ?? activeObject}</div>
                {columnParent && (
                  <div className="text-[10px] text-td-gray-dark mt-0.5">
                    Column <span className="font-mono">{columnParent.split(".").pop()}</span> has no usage of its own — showing its parent table.
                  </div>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={clearFocus}
              className="text-td-gray-dark hover:text-td-navy shrink-0"
              aria-label="Clear focus"
            >
              <X size={16} />
            </button>
          </div>

          {!selectedSnap ? (
            <p className="text-xs text-td-gray-dark">Select a snapshot above to load this object&apos;s usage and criticality.</p>
          ) : !detail ? (
            <p className="text-xs text-td-gray-dark">Loading object profile…</p>
          ) : !detail.found ? (
            <p className="text-xs text-td-gray-dark">
              No usage telemetry or criticality found for this object in snapshot #{selectedSnap}
              {" "}(common for schemas and parser-only imports).
            </p>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <div className="bg-gray-50 rounded p-2">
                <div className="text-[10px] text-td-gray-dark">Queries</div>
                <div className="text-lg font-bold text-td-navy">{detail.usage.query_count.toLocaleString()}</div>
              </div>
              <div className="bg-gray-50 rounded p-2">
                <div className="text-[10px] text-td-gray-dark">Distinct users</div>
                <div className="text-lg font-bold text-td-navy">{detail.usage.user_count.toLocaleString()}</div>
              </div>
              <div className="bg-gray-50 rounded p-2">
                <div className="text-[10px] text-td-gray-dark">Last accessed</div>
                <div className="text-xs font-medium text-td-navy mt-1">
                  {detail.usage.last_accessed
                    ? new Date(detail.usage.last_accessed).toLocaleDateString()
                    : "—"}
                </div>
              </div>
              <div className="bg-gray-50 rounded p-2">
                <div className="text-[10px] text-td-gray-dark">Criticality</div>
                {detail.criticality ? (
                  <span
                    className="inline-flex mt-1 px-2 py-0.5 rounded-full text-[11px] font-medium text-white"
                    style={{ backgroundColor: critColor(detail.criticality.criticality_level) }}
                  >
                    {detail.criticality.criticality_level} · {(detail.criticality.combined_score * 100).toFixed(0)}%
                  </span>
                ) : (
                  <div className="text-xs text-td-gray-dark mt-1">—</div>
                )}
              </div>
              <div className="bg-gray-50 rounded p-2 flex items-center">
                <Link
                  href={`/lineage?object=${encodeURIComponent(resolvedObject ?? activeObject)}&snapshot=${selectedSnap}`}
                  className="inline-flex items-center gap-1 text-xs font-medium text-td-object hover:underline"
                >
                  <GitBranch size={12} /> View lineage
                </Link>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Snapshot selector for criticality */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <label className="text-xs text-td-gray-dark block mb-1">Analyze criticality for</label>
            <select
              value={selectedSnap}
              onChange={(e) => { if (e.target.value) loadCriticality(e.target.value); }}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm w-full"
            >
              <option value="">Select a snapshot...</option>
              {activeDiffPair && (
                <option value={String(activeDiffPair.snapshotTo)}>
                  ⚡ Current diff target — Snapshot #{activeDiffPair.snapshotTo} (from diff #{activeDiffPair.snapshotFrom} → #{activeDiffPair.snapshotTo})
                </option>
              )}
              {snapshots.map((s) => (
                <option key={s.snapshot_id} value={s.snapshot_id}>
                  Snapshot #{s.snapshot_id} — {s.source_system} — {new Date(s.created_at).toLocaleDateString()}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {error && <ErrorAlert message={error} />}
      {loading && <LoadingSpinner />}

      {/* Export buttons */}
      <div className="flex items-center gap-3 mb-4">
        <a
          href={`${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1"}/export/usage`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 bg-green-600 text-white px-3 py-1.5 rounded text-xs font-medium hover:bg-green-700 transition-colors"
        >
          <Download size={12} />
          Export Usage CSV
        </a>
        {criticality && (
          <a
            href={`${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1"}/export/intelligence/${criticality.snapshot_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 bg-green-600 text-white px-3 py-1.5 rounded text-xs font-medium hover:bg-green-700 transition-colors"
          >
            <Download size={12} />
            Export Criticality CSV
          </a>
        )}
      </div>

      {/* ═══════════════════════════════════════════════════════════
          SECTION 1 · Usage footprint
          ═══════════════════════════════════════════════════════════ */}
      {usage && usage.length > 0 && (
        <GuidedSection
          title="1. Usage footprint"
          subtitle={activeObject
            ? `Global top 12 by query count — see the Object drill-down card above for "${(resolvedObject ?? activeObject).split(".").pop() ?? ""}" specifically`
            : "How heavily each object is queried (top 12 by query count)"}
          icon={Flame}
          intro={
            <>
              This is raw usage telemetry — how many queries touched each object in the
              observed window. Think of it as "which tables are load-bearing for the business."
              An object with high usage and low graph centrality may still be critical
              (it&apos;s a leaf report used by everyone); an object with zero usage may be safe
              to decommission even if it has many upstream producers.
              {activeObject && !usage?.some(u => isFocused(u.object_name)) && (
                <>{" "}<strong>Note:</strong> {resolvedObject ?? activeObject} is not in the top 12 — its stats are in the Object drill-down card above.</>
              )}
            </>
          }
        >
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
            <div className="space-y-2">
              {/* Match both fully-qualified ("db.tbl") and bare ("tbl") forms
                  — other pages sometimes pass just the object leaf name via
                  the ?object= query param. */}
              {usage.slice(0, 12).map((u) => {
                const focused = isFocused(u.object_name);
                return (
                <div
                  key={u.object_name}
                  onClick={() => focusObject(u.object_name)}
                  className={`flex items-center gap-3 cursor-pointer rounded -mx-2 px-2 py-1 ${focused ? "bg-td-orange/10" : "hover:bg-gray-50"}`}
                  title="Click to drill into this object"
                >
                  <span className={`text-xs font-mono w-48 truncate ${focused ? "text-td-orange font-bold" : "text-td-gray-dark"}`} title={u.object_name}>
                    {u.object_name}
                  </span>
                  <div className="flex-1">
                    <HeatBar value={u.query_count} max={maxQueries} />
                  </div>
                </div>
                );
              })}
            </div>
          </div>
        </GuidedSection>
      )}

      {/* ═══════════════════════════════════════════════════════════
          SECTION 2 · Criticality overview
          ═══════════════════════════════════════════════════════════ */}
      {criticality && (
        <GuidedSection
          title="2. Criticality overview"
          subtitle="Which objects are business-critical for this snapshot"
          icon={Shield}
          intro={
            <>
              SCION blends <strong>usage</strong> (how often queried) with <strong>graph
              centrality</strong> (how many downstream objects depend on it) into a single
              <strong> criticality score</strong>. An object is HIGH if score ≥ 70%, MEDIUM
              if 30–70%, LOW below. KPIs count how many objects fall in each tier; the
              heatmap below gives the visual shape — clusters of red cells tell you where
              a change would hit hardest.
            </>
          }
        >
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <KpiCard label="Total Objects" value={criticality.total} />
            <KpiCard label="HIGH Criticality" value={criticality.high_count} color="#DC2626" />
            <KpiCard label="MEDIUM Criticality" value={criticality.medium_count} color="#F59E0B" />
            <KpiCard label="LOW Criticality" value={criticality.low_count} color="#16A34A" />
          </div>

          {critByLevel.length > 0 && (
            <div className="mb-4">
              <DonutChart
                title="Criticality distribution"
                data={critByLevel}
                colors={critByLevel.map((d) => CRIT_COLORS[d.name] ?? "#7C8185")}
              />
            </div>
          )}

          {criticality.items.length > 0 && (
            <RiskHeatmap
              title="Object criticality heatmap"
              description="One cell = one object (not a time bucket). Hover a cell for its usage and graph-centrality breakdown."
              items={criticality.items.map((item) => ({
                name: item.object_name,
                score: item.combined_score,
                level: item.criticality_level,
                detail: `Usage: ${(item.usage_score * 100).toFixed(0)}% | Graph: ${(item.graph_score * 100).toFixed(0)}%`,
              }))}
            />
          )}
        </GuidedSection>
      )}

      {/* ═══════════════════════════════════════════════════════════
          SECTION 3 · Per-object drill-down
          ═══════════════════════════════════════════════════════════ */}
      {criticality && criticality.items.length > 0 && (
        <GuidedSection
          title="3. Per-object drill-down"
          subtitle={activeObject
            ? `Global criticality ranking — ${(resolvedObject ?? activeObject).split(".").pop()} is ${criticality.items.some(i => isFocused(i.object_name)) ? "highlighted below" : "in the Object drill-down card above"}`
            : "The raw numbers behind the score, row by row"}
          icon={ListTree}
          intro={
            <>
              <strong>Usage Score</strong> = 60% query_count + 40% user_count, normalised to the
              busiest object in the system. <strong>Graph Score</strong> = normalised in_degree +
              out_degree + centrality.{" "}
              <strong>Combined</strong> = 0.6 × Usage + 0.4 × Graph → the tier in the last column.
              A row with high Usage but low Graph is "popular but isolated" (safe-ish to change);
              high Graph but low Usage is "structurally central but unused" (probably dead code
              nobody noticed).
            </>
          }
        >
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-td-navy text-white text-left">
                <th className="px-4 py-3 font-medium">Object</th>
                <th className="px-4 py-3 font-medium">
                  <span className="inline-flex items-center gap-1">Usage Score <InfoTooltip text="Normalized 0-100% score based on how many queries and users access this object." detail="Formula: 60% query_count + 40% user_count, scaled to 0-1." size={11} className="text-white/50" /></span>
                </th>
                <th className="px-4 py-3 font-medium">
                  <span className="inline-flex items-center gap-1">Graph Score <InfoTooltip text="Normalized 0-100% score based on how connected this object is in the dependency graph." detail="Formula: combines in_degree + out_degree + centrality. Higher = more downstream/upstream dependencies." size={11} className="text-white/50" /></span>
                </th>
                <th className="px-4 py-3 font-medium">
                  <span className="inline-flex items-center gap-1">Combined <InfoTooltip text="Overall criticality score." detail="Formula: 60% Usage Score + 40% Graph Score. Level: >70% HIGH, 30-70% MEDIUM, <30% LOW." size={11} className="text-white/50" /></span>
                </th>
                <th className="px-4 py-3 font-medium">
                  <span className="inline-flex items-center gap-1">Criticality <InfoTooltip text="Business criticality level derived from the combined score." detail="HIGH = critical objects (high usage + many dependents). MEDIUM = moderate. LOW = low risk if broken." size={11} className="text-white/50" /></span>
                </th>
              </tr>
            </thead>
            <tbody>
              {criticality.items.map((item) => (
                <tr
                  key={item.object_name}
                  onClick={() => focusObject(item.object_name)}
                  className={`border-t border-gray-100 cursor-pointer ${isFocused(item.object_name) ? "bg-td-orange/10" : "hover:bg-gray-50"}`}
                  title="Click to drill into this object"
                >
                  <td className="px-4 py-3 font-mono text-xs">{item.object_name}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-2 bg-gray-100 rounded-full overflow-hidden">
                        <div className="h-full bg-td-object rounded-full" style={{ width: `${item.usage_score * 100}%` }} />
                      </div>
                      <span className="text-xs text-td-gray-dark">{(item.usage_score * 100).toFixed(0)}%</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-2 bg-gray-100 rounded-full overflow-hidden">
                        <div className="h-full bg-td-navy rounded-full" style={{ width: `${item.graph_score * 100}%` }} />
                      </div>
                      <span className="text-xs text-td-gray-dark">{(item.graph_score * 100).toFixed(0)}%</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 font-bold text-xs">
                    {(item.combined_score * 100).toFixed(0)}%
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className="inline-flex px-2 py-0.5 rounded-full text-xs font-medium text-white"
                      style={{ backgroundColor: CRIT_COLORS[item.criticality_level] ?? "#7C8185" }}
                    >
                      {item.criticality_level}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        </GuidedSection>
      )}

      {!usage && !criticality && !loading && (
        <EmptyState message="No usage data ingested yet. Use POST /api/v1/usage/ingest to load data." />
      )}
    </PageShell>
  );
}
