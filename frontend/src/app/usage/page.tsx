"use client";

import { useState, useEffect, useMemo, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import PageShell from "@/components/layout/PageShell";
import KpiCard from "@/components/shared/KpiCard";
import DonutChart from "@/components/shared/DonutChart";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { useSelection } from "@/lib/SelectionContext";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { getUsageSummary, getCriticality } from "@/lib/api/usage";
import type { CriticalityResponse, UsageSummaryItem } from "@/lib/api/types";
import { Shield, Flame, Download, ListTree } from "lucide-react";
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
  // highlights that row in both the heatmap and the criticality table below.
  const searchParams = useSearchParams();
  const focusedObject = searchParams.get("object");

  // Usage summary is global (not tied to a snapshot) so load once on mount.
  // Failures are swallowed because usage is optional — criticality still works.
  useEffect(() => {
    getUsageSummary()
      .then((d) => setUsage(d.items))
      .catch(() => {});
  }, []);

  // Auto-seed criticality from an active diff, but ONLY if the user hasn't
  // already picked a snapshot manually — hence the `!selectedSnap` guard.
  // `selectedSnap` is deliberately omitted from deps to prevent re-seeding
  // after the user manually clears or changes it.
  useEffect(() => {
    if (activeDiffPair && !selectedSnap) {
      loadCriticality(String(activeDiffPair.snapshotTo));
    }
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
  const focusMatch = focusedObject && (
    (usage?.some(u => u.object_name === focusedObject || focusedObject.endsWith("." + u.object_name))) ||
    (criticality?.items.some(i => i.object_name === focusedObject || focusedObject.endsWith("." + i.object_name)))
  );

  return (
    <PageShell title="Usage & Criticality" subtitle="Object usage frequency and business criticality">
      {/* Focused object banner from quick-link navigation. When we can't
          find the object in any of our datasets (happens for schemas and
          parser-only objects with no usage telemetry), we shift the copy
          from a promise ("highlighted below") to an explanation so the
          user isn't confused about why nothing lit up. */}
      {focusedObject && (
        <div className="bg-td-orange/10 border border-td-orange/30 rounded-lg p-3 mb-4 flex items-center gap-3">
          <Flame size={16} className="text-td-orange shrink-0" />
          <div className="flex-1 text-xs">
            <span className="text-td-gray-dark">Focused on:</span>{" "}
            <span className="font-mono font-semibold text-td-navy">{focusedObject}</span>
            <span className="text-td-gray-dark ml-2">
              {focusMatch
                ? "— highlighted in the tables below."
                : "— no usage telemetry found for this object (common for schemas and parser-only imports). The tables below show the objects we do have data for."}
            </span>
          </div>
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
          subtitle="How heavily each object is queried (top 12 by query count)"
          icon={Flame}
          intro={
            <>
              This is raw usage telemetry — how many queries touched each object in the
              observed window. Think of it as “which tables are load-bearing for the business.”
              An object with high usage and low graph centrality may still be critical
              (it&apos;s a leaf report used by everyone); an object with zero usage may be safe
              to decommission even if it has many upstream producers.
            </>
          }
        >
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
            <div className="space-y-2">
              {/* Match both fully-qualified ("db.tbl") and bare ("tbl") forms
                  — other pages sometimes pass just the object leaf name via
                  the ?object= query param. */}
              {usage.slice(0, 12).map((u) => {
                const isFocused = focusedObject === u.object_name || focusedObject?.endsWith("." + u.object_name);
                return (
                <div key={u.object_name} className={`flex items-center gap-3 ${isFocused ? "bg-td-orange/10 -mx-2 px-2 py-1 rounded" : ""}`}>
                  <span className={`text-xs font-mono w-48 truncate ${isFocused ? "text-td-orange font-bold" : "text-td-gray-dark"}`} title={u.object_name}>
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
          subtitle="The raw numbers behind the score, row by row"
          icon={ListTree}
          intro={
            <>
              <strong>Usage Score</strong> = 60% query_count + 40% user_count, normalised to the
              busiest object in the system. <strong>Graph Score</strong> = normalised in_degree +
              out_degree + centrality.{" "}
              <strong>Combined</strong> = 0.6 × Usage + 0.4 × Graph → the tier in the last column.
              A row with high Usage but low Graph is “popular but isolated” (safe-ish to change);
              high Graph but low Usage is “structurally central but unused” (probably dead code
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
                <tr key={item.object_name} className={`border-t border-gray-100 hover:bg-gray-50 ${(focusedObject === item.object_name || focusedObject?.endsWith("." + item.object_name)) ? "bg-td-orange/10" : ""}`}>
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
