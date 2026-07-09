"use client";

import { useState, useEffect, useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
  LineChart, Line,
} from "recharts";
import PageShell from "@/components/layout/PageShell";
import AnimatedCounter from "@/components/shared/AnimatedCounter";
import KpiCard from "@/components/shared/KpiCard";
import DonutChart from "@/components/shared/DonutChart";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { useSelection } from "@/lib/SelectionContext";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { getScorecard, getDomainRisk, getCoChange, getVolatilityTrend } from "@/lib/api/intelligence";
import type { CoChangeResponse, VolatilityTrendResponse, SchemaVolatilityTrend } from "@/lib/api/types";
import {
  Shield, AlertTriangle, Heart, Layers, Download,
  CheckCircle, XCircle, Info, TrendingUp, TrendingDown, Minus,
  Link2, Activity, ArrowUp, ArrowDown, ArrowRight, BarChart3,
} from "lucide-react";
import { GuidedSection } from "@/components/shared/GuidedSection";
import InfoTooltip from "@/components/shared/InfoTooltip";

const HEALTH_COLORS: Record<string, string> = {
  HEALTHY: "#16A34A",
  AT_RISK: "#F59E0B",
  CRITICAL: "#DC2626",
};

const HEALTH_ICONS: Record<string, typeof CheckCircle> = {
  HEALTHY: CheckCircle,
  AT_RISK: AlertTriangle,
  CRITICAL: XCircle,
};

const STABILITY_LABELS: Record<string, string> = {
  HEALTHY: "Stable",
  AT_RISK: "Volatile",
  CRITICAL: "Highly Volatile",
};

const HEALTH_DESCRIPTIONS: Record<string, string> = {
  HEALTHY: "This database is structurally stable. Few changes detected and no critical breaking changes.",
  AT_RISK: "This database shows moderate structural volatility. Some breaking changes or high-risk domains should be reviewed.",
  CRITICAL: "This database is highly volatile. Multiple breaking changes and high-risk areas detected — review before next release.",
};

const RISK_COLORS: Record<string, string> = {
  HIGH: "#DC2626",
  MEDIUM: "#F59E0B",
  LOW: "#16A34A",
};

function volatilityLabel(v: number): { text: string; color: string; icon: typeof TrendingUp } {
  if (v > 0.15) return { text: "High volatility — frequent structural changes", color: "#DC2626", icon: TrendingUp };
  if (v > 0.05) return { text: "Moderate volatility — some structural changes", color: "#F59E0B", icon: Minus };
  return { text: "Stable — minimal structural changes", color: "#16A34A", icon: TrendingDown };
}

export default function IntelligencePage() {
  const { activeDiffPair } = useSelection();
  const { data: snapData } = useSnapshots();
  const snapshots = snapData?.snapshots ?? [];

  const [selectedSnap, setSelectedSnap] = useState<string>("");
  const [scorecard, setScorecard] = useState<any>(null);
  const [domainRisks, setDomainRisks] = useState<any>(null);
  const [coChange, setCoChange] = useState<CoChangeResponse | null>(null);
  const [volTrend, setVolTrend] = useState<VolatilityTrendResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dbFilter, setDbFilter] = useState<string>("");

  // Auto-analyze the TO-side of the active diff, but only if we don't have a
  // scorecard yet — otherwise we'd clobber a manual selection every time
  // context updates. The `scorecard` guard also prevents duplicate loads.
  useEffect(() => {
    if (activeDiffPair && !scorecard) {
      loadData(String(activeDiffPair.snapshotTo));
    }
  }, [activeDiffPair]);

  // Scorecard + per-domain risk are independent endpoints; fetch in parallel
  // so the page reaches its final state in one round-trip.
  async function loadData(snapId: string) {
    setLoading(true);
    setError(null);
    setSelectedSnap(snapId);
    setDbFilter("");
    try {
      // v1.07: fetch the DS-pack endpoints alongside the classic scorecard.
      // `allSettled` so a failure in one (e.g. cochange with no pairs yet)
      // doesn't blank the whole page.
      const [sc, dr, cc, vt] = await Promise.allSettled([
        getScorecard(Number(snapId)),
        getDomainRisk(Number(snapId)),
        getCoChange(1.5, 2, 25),
        getVolatilityTrend(3),
      ]);
      if (sc.status === "fulfilled") setScorecard(sc.value);
      if (dr.status === "fulfilled") setDomainRisks(dr.value);
      if (cc.status === "fulfilled") setCoChange(cc.value);
      if (vt.status === "fulfilled") setVolTrend(vt.value);
      if (sc.status === "rejected") throw sc.reason;
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setLoading(false);
    }
  }

  const DOMAIN_CHART_TOP = 20;
  // Max domain cards to render — prevents mounting hundreds of SVG sparklines
  // simultaneously on large catalogs (Transcend has 300+ schemas).
  const DOMAIN_CARDS_MAX = 100;

  const volByDomain = useMemo<Record<string, SchemaVolatilityTrend>>(() => {
    const map: Record<string, SchemaVolatilityTrend> = {};
    for (const t of volTrend?.trends ?? []) map[t.schema_name] = t;
    return map;
  }, [volTrend]);

  const healthColor = scorecard ? HEALTH_COLORS[scorecard.overall_health] ?? "#7C8185" : "#7C8185";
  const HealthIcon = scorecard ? HEALTH_ICONS[scorecard.overall_health] ?? Info : Info;

  const dbFilterQ = dbFilter.trim().toLowerCase();

  const domainChartDataAll = useMemo(() =>
    (domainRisks?.domains ?? [])
      .filter((d: any) => !dbFilterQ || d.schema_name.toLowerCase().includes(dbFilterQ))
      .map((d: any) => ({
        name: d.schema_name,
        score: Math.round(d.risk_score * 100),
        color: RISK_COLORS[d.risk_level] ?? "#7C8185",
      }))
      .sort((a: any, b: any) => b.score - a.score),
  [domainRisks, dbFilterQ]);

  const domainChartData = useMemo(() => domainChartDataAll.slice(0, DOMAIN_CHART_TOP), [domainChartDataAll]);

  const filteredDomains = useMemo(() =>
    (domainRisks?.domains ?? []).filter(
      (d: any) => !dbFilterQ || d.schema_name.toLowerCase().includes(dbFilterQ)
    ),
  [domainRisks, dbFilterQ]);

  // Cap cards to avoid mounting hundreds of Recharts SVGs at once.
  const visibleDomains = useMemo(() => filteredDomains.slice(0, DOMAIN_CARDS_MAX), [filteredDomains]);

  const riskDonutData = useMemo(() => {
    const dist = (domainRisks?.domains ?? []).reduce(
      (acc: Record<string, number>, d: any) => {
        acc[d.risk_level] = (acc[d.risk_level] ?? 0) + 1;
        return acc;
      },
      {} as Record<string, number>,
    );
    return Object.entries(dist).map(([name, value]) => ({ name, value: value as number }));
  }, [domainRisks]);

  const vol = scorecard ? volatilityLabel(scorecard.volatility_index) : null;
  const VolIcon = vol?.icon ?? Minus;

  return (
    <PageShell title="Governance Report" subtitle="How stable is your data warehouse structure?">
      {/* Selector */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        <div className="flex items-center gap-3">
          <Shield size={18} className="text-td-navy" />
          <div className="flex-1">
            <label className="text-xs text-td-gray-dark block mb-1">Select a snapshot to analyze</label>
            <select value={selectedSnap}
              onChange={(e) => { if (e.target.value) loadData(e.target.value); }}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm w-full max-w-md">
              <option value="">Choose a snapshot...</option>
              {snapshots.map((s) => (
                <option key={s.snapshot_id} value={s.snapshot_id}>
                  Snapshot #{s.snapshot_id} — {s.source_system} — {new Date(s.created_at).toLocaleDateString()}
                </option>
              ))}
            </select>
          </div>
          {selectedSnap && (
            <a
              href={`${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1"}/export/intelligence/${selectedSnap}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 bg-green-600 text-white px-3 py-1.5 rounded text-xs font-medium hover:bg-green-700 transition-colors self-end"
            >
              <Download size={12} />
              Export CSV
            </a>
          )}
        </div>
      </div>

      {error && <ErrorAlert message={error} />}
      {loading && <LoadingSpinner />}

      {scorecard && (
        <>
          {/* ═══ SECTION 1: Overall Health ═══ */}
          <div className="bg-white rounded-xl shadow-sm border-2 p-6 mb-6" style={{ borderColor: healthColor }}>
            <div className="flex items-start gap-5">
              <div
                className="w-16 h-16 rounded-2xl flex items-center justify-center shrink-0"
                style={{ backgroundColor: `${healthColor}15` }}
              >
                <HealthIcon size={32} style={{ color: healthColor }} />
              </div>
              <div className="flex-1">
                <div className="text-xs text-td-gray-dark uppercase tracking-wider mb-1 flex items-center gap-1.5" title="Measures structural stability based on number of changes, breaking changes, downstream impacts, and critical objects affected.">
                  Structural Stability
                  <span className="bg-gray-200 text-gray-600 rounded-full w-4 h-4 inline-flex items-center justify-center text-[9px] cursor-help">?</span>
                </div>
                <div className="text-2xl font-bold mb-1" style={{ color: healthColor }}>
                  {STABILITY_LABELS[scorecard.overall_health] ?? "Unknown"}
                </div>
                <p className="text-sm text-gray-600 leading-relaxed">
                  {HEALTH_DESCRIPTIONS[scorecard.overall_health] ?? "Status unknown."}
                </p>
              </div>
              <div className="text-right shrink-0">
                <div className="text-xs text-td-gray-dark mb-0.5" title="100% = perfectly stable (no breaking changes). 0% = highly unstable.">
                  Health Score
                </div>
                <div className="text-[10px] text-td-gray-dark mb-1 opacity-70">higher = more stable</div>
                <div className="flex items-center gap-3">
                  <AnimatedCounter
                    value={Math.round(scorecard.health_score * 100)}
                    className="text-4xl font-bold"
                    style={{ color: healthColor }}
                    suffix="%"
                  />
                </div>
                <div className="w-32 h-3 bg-gray-100 rounded-full overflow-hidden mt-2">
                  <div
                    className="h-full rounded-full transition-all duration-1000"
                    style={{ width: `${scorecard.health_score * 100}%`, backgroundColor: healthColor }}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 1 · Governance KPIs
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="1. What SCION found in this snapshot"
            subtitle="The five numbers that drive the stability score above"
            icon={Info}
            intro={
              <>
                <strong>Objects monitored</strong> = total catalog size.
                <strong> Changes detected</strong> = structural deltas vs the previous snapshot.
                <strong> Breaking changes</strong> are the subset of those that will break
                downstream consumers (dropped columns referenced by views, incompatible type changes).
                <strong> Downstream impacts</strong> counts how many objects transitively feel at least
                one change. <strong>High criticality</strong> is the number of high-query or high-centrality
                objects caught in the ripple.
              </>
            }
          >
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
              <div className="text-[10px] text-td-gray-dark uppercase tracking-wider">Objects monitored</div>
              <AnimatedCounter value={scorecard.total_objects} className="text-2xl font-bold text-td-navy block mt-1" />
              <div className="text-[10px] text-td-gray-dark mt-1">
                {scorecard.schema_count} databases, {scorecard.table_count} tables
              </div>
            </div>
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
              <div className="text-[10px] text-td-gray-dark uppercase tracking-wider">Changes detected</div>
              <AnimatedCounter value={scorecard.total_changes} className="text-2xl font-bold text-td-orange block mt-1" />
              <div className="text-[10px] text-td-gray-dark mt-1">
                across all compared snapshots
              </div>
            </div>
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
              <div className="text-[10px] text-td-gray-dark uppercase tracking-wider">Breaking changes</div>
              <AnimatedCounter value={scorecard.breaking_changes} className="text-2xl font-bold block mt-1" style={{ color: scorecard.breaking_changes > 0 ? "#DC2626" : "#16A34A" }} />
              <div className="text-[10px] text-td-gray-dark mt-1">
                {scorecard.breaking_changes > 0 ? "require review before deploy" : "none — safe to proceed"}
              </div>
            </div>
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
              <div className="text-[10px] text-td-gray-dark uppercase tracking-wider">Downstream impacts</div>
              <AnimatedCounter value={scorecard.total_impacts} className="text-2xl font-bold text-td-object block mt-1" />
              <div className="text-[10px] text-td-gray-dark mt-1">
                objects affected by changes
              </div>
            </div>
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
              <div className="text-[10px] text-td-gray-dark uppercase tracking-wider">High criticality</div>
              <AnimatedCounter value={scorecard.high_criticality_objects} className="text-2xl font-bold block mt-1" style={{ color: scorecard.high_criticality_objects > 0 ? "#DC2626" : "#16A34A" }} />
              <div className="text-[10px] text-td-gray-dark mt-1">
                most-used objects at risk
              </div>
            </div>
          </div>
          </GuidedSection>

          {/* ═══ System stability callout — separate from section wrapper because
              it's a single-row visual indicator, not a multi-element block ═══ */}
          {vol && (
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6 flex items-center gap-4">
              <div className="w-10 h-10 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${vol.color}15` }}>
                <VolIcon size={20} style={{ color: vol.color }} />
              </div>
              <div className="flex-1">
                <div className="text-xs text-td-gray-dark uppercase tracking-wider">Schema Churn Rate</div>
                <div className="text-sm font-medium" style={{ color: vol.color }}>{vol.text}</div>
              </div>
              <div className="text-right">
                <div className="text-xs text-td-gray-dark flex items-center justify-end gap-1">
                  Volatility Index
                  <InfoTooltip
                    text="Ratio of changed objects to total objects between the two most recent snapshots. Lower = less churn = more stable. Capped at 100% for readability — a raw ratio above 1.0 (more changes than objects, e.g. many column-level changes per table) shows as 100% with the exact ratio in this tooltip."
                    detail={
                      scorecard.volatility_index > 1
                        ? `Raw ratio: ${(scorecard.volatility_index * 100).toFixed(0)}% (uncapped)`
                        : undefined
                    }
                    size={11}
                  />
                </div>
                <AnimatedCounter
                  value={Math.min(scorecard.volatility_index * 100, 100)}
                  className="text-xl font-bold"
                  style={{ color: vol.color }}
                  suffix="%"
                  decimals={1}
                />
                <div className="text-[10px] text-td-gray-dark mt-0.5 opacity-70">lower = less churn</div>
              </div>
            </div>
          )}

          {/* ═══════════════════════════════════════════════════════════
              SECTION 2 · Database-level risk breakdown
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="2. Which databases need attention?"
            subtitle="Per-domain risk score, distribution, and drill-down cards"
            icon={Layers}
            intro={
              <>
                Each database gets a <strong>risk score</strong> (0–100%) based on its
                share of changes, breaking-counts, downstream impacts, and critical
                objects. The bar chart on the left ranks them; the donut on the right
                shows how many sit in each risk tier (HIGH/MEDIUM/LOW).
                Cards below drill into each one — including the volatility sparkline
                so you can see if the risk is trending up or down.
              </>
            }
          >
          {/* Database filter */}
          <div className="relative mb-4 max-w-sm">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-td-gray-dark">
              <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
            </svg>
            <input
              type="text"
              value={dbFilter}
              onChange={(e) => setDbFilter(e.target.value)}
              placeholder="Filter by database name…"
              className="w-full border border-gray-300 rounded pl-8 pr-8 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-td-navy/30 focus:border-td-navy"
            />
            {dbFilter && (
              <button
                onClick={() => setDbFilter("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-td-gray-dark hover:text-td-navy"
                title="Clear filter"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            )}
          </div>
          {dbFilter && (
            <p className="text-[11px] text-td-gray-dark mb-3">
              <strong className="text-td-navy">{filteredDomains.length.toLocaleString()}</strong> of {(domainRisks?.domains ?? []).length.toLocaleString()} databases match
            </p>
          )}

          <div className="grid grid-cols-2 gap-6 mb-6">
            {/* Risk bar chart */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-td-navy">Risk Score by Database</h3>
                {domainChartDataAll.length > DOMAIN_CHART_TOP && (
                  <span className="text-[11px] text-td-gray-dark">
                    Top {DOMAIN_CHART_TOP} of {domainChartDataAll.length.toLocaleString()}
                  </span>
                )}
              </div>
              {domainChartData.length > 0 ? (() => {
                const chartHeight = Math.min(500, Math.max(200, domainChartData.length * 24));
                return (
                  <div style={{ height: chartHeight }}>
                    <ResponsiveContainer width="100%" height={chartHeight}>
                      <BarChart data={domainChartData} layout="vertical">
                        <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10 }} />
                        <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={120} />
                        <Tooltip formatter={(value) => [`${value}%`, "Risk Score"]} />
                        <Bar dataKey="score" radius={[0, 4, 4, 0]}>
                          {domainChartData.map((entry: any, i: number) => (
                            <Cell key={i} fill={entry.color} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                );
              })() : (
                <p className="text-xs text-td-gray-dark">No domain data</p>
              )}
            </div>

            {/* Risk donut */}
            {riskDonutData.length > 0 && (
              <DonutChart
                title="How many databases at each risk level?"
                data={riskDonutData}
                colors={riskDonutData.map((d: any) => RISK_COLORS[d.name] ?? "#7C8185")}
              />
            )}
          </div>

          {/* Domain detail cards instead of raw table */}
          {domainRisks && filteredDomains.length > 0 && (
            <>
            {filteredDomains.length > DOMAIN_CARDS_MAX && (
              <p className="text-[11px] text-td-gray-dark mb-3">
                Showing first <strong className="text-td-navy">{DOMAIN_CARDS_MAX}</strong> of {filteredDomains.length.toLocaleString()} databases. Use the filter above to narrow results.
              </p>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
              {visibleDomains.map((d: any) => {
                const riskColor = RISK_COLORS[d.risk_level] ?? "#7C8185";
                return (
                  <div key={d.schema_name} className="bg-white rounded-lg shadow-sm border-l-4 border-gray-200 p-4" style={{ borderLeftColor: riskColor }}>
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Layers size={14} style={{ color: riskColor }} />
                        <span className="text-sm font-semibold text-td-navy">{d.schema_name}</span>
                      </div>
                      <span
                        className="px-2.5 py-1 rounded-full text-xs font-bold text-white"
                        style={{ backgroundColor: riskColor }}
                      >
                        {d.risk_level} RISK
                      </span>
                    </div>

                    <div className="grid grid-cols-4 gap-3 text-center">
                      <div>
                        <div className="text-lg font-bold text-td-navy">{d.change_count}</div>
                        <div className="text-[9px] text-td-gray-dark">changes</div>
                      </div>
                      <div>
                        <div className="text-lg font-bold" style={{ color: d.breaking_count > 0 ? "#DC2626" : "#16A34A" }}>
                          {d.breaking_count}
                        </div>
                        <div className="text-[9px] text-td-gray-dark">breaking</div>
                      </div>
                      <div>
                        <div className="text-lg font-bold text-td-object">{d.impact_count}</div>
                        <div className="text-[9px] text-td-gray-dark">impacts</div>
                      </div>
                      <div>
                        <div className="text-lg font-bold text-td-orange">{(d.risk_score * 100).toFixed(0)}%</div>
                        <div className="text-[9px] text-td-gray-dark">risk score</div>
                      </div>
                    </div>

                    {/* ──── v1.07 volatility trend mini-chart ────
                        Enriches the point-in-time risk score with a rolling
                        volatility series + current/prior delta so readers see
                        trajectory, not just current state. Only renders when
                        the DS-pack endpoint returned data for this schema. */}
                    {volByDomain[d.schema_name] && (() => {
                      const vt = volByDomain[d.schema_name];
                      const trendColor = vt.trend === "worsening" ? "#DC2626" : vt.trend === "improving" ? "#16A34A" : "#64748B";
                      const TrendIcon = vt.trend === "worsening" ? ArrowUp : vt.trend === "improving" ? ArrowDown : ArrowRight;
                      return (
                        <div className="mt-3 flex items-center gap-3 bg-gray-50 rounded-lg p-2 border border-gray-100">
                          {/* Explicit pixel dimensions (96×32, matches the
                              old `w-24 h-8` wrapper) because ResponsiveContainer
                              with `height="100%"` can race the layout engine
                              and pass -1 to the underlying LineChart on first
                              render, producing noisy console warnings. Since
                              we know the sparkline size at design time, skip
                              the DOM measurement entirely. */}
                          <div className="shrink-0">
                            <LineChart width={96} height={32} data={vt.series}>
                              <Line
                                type="monotone"
                                dataKey="volatility"
                                stroke={trendColor}
                                strokeWidth={1.5}
                                dot={false}
                                isAnimationActive={false}
                              />
                            </LineChart>
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="text-[10px] text-td-gray-dark uppercase tracking-wider">
                              Volatility trend ({vt.window}-snap rolling)
                            </div>
                            <div className="flex items-center gap-1 text-[11px]">
                              <span className="font-mono text-td-navy">{(vt.current_volatility * 100).toFixed(0)}%</span>
                              <TrendIcon size={11} style={{ color: trendColor }} />
                              <span className="font-medium" style={{ color: trendColor }}>
                                {vt.delta_pct > 0 ? "+" : ""}{vt.delta_pct.toFixed(0)}% vs prior
                              </span>
                            </div>
                          </div>
                        </div>
                      );
                    })()}

                    {/* Progress bar */}
                    <div className="mt-3 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full rounded-full" style={{ width: `${d.risk_score * 100}%`, backgroundColor: riskColor }} />
                    </div>

                    {/* Human-readable summary */}
                    <p className="text-[11px] text-td-gray-dark mt-2">
                      {d.risk_level === "HIGH"
                        ? `This database has ${d.breaking_count} breaking change(s) and ${d.impact_count} downstream impact(s). Review urgently.`
                        : d.risk_level === "MEDIUM"
                          ? `Some changes detected. ${d.breaking_count > 0 ? `${d.breaking_count} breaking.` : "No breaking changes."} Monitor closely.`
                          : "This database is stable with minimal changes. No action needed."}
                    </p>
                  </div>
                );
              })}
            </div>
            </>
          )}
          </GuidedSection>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 3 · Historical co-change patterns (v1.07 DS-pack)
              Association rules from the full change_event history —
              surfaces couplings invisible to the lineage graph.
              ═══════════════════════════════════════════════════════════ */}
          {coChange && coChange.pairs.length > 0 && (
            <GuidedSection
              title="3. Historical co-change patterns"
              subtitle="What changes together — beyond what the lineage graph can see"
              icon={Link2}
              intro={
                <>
                  Market-basket analysis over the full change history (Apriori pairwise).
                  If table A and table B have changed in the same release N times, we score the
                  coupling with <strong>confidence</strong> (P(B changes | A changes)) and{" "}
                  <strong>lift</strong> (how much more often than random chance). Lift ≥ 2 means
                  real coupling; ≥ 3 is strong. Useful for catching shared-team ownership,
                  DEV/UAT/PROD triplets, or business-domain conventions that aren&apos;t SQL-lineage.
                </>
              }
            >
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] text-td-gray-dark">
                  Thresholds: lift ≥ {coChange.min_lift}, min pair support {coChange.min_pair_support}
                </span>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-100 text-indigo-700">
                  {coChange.total} rules
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-[10px] uppercase tracking-wider text-td-gray-dark border-b">
                      <th className="py-2 pr-2">When this changes…</th>
                      <th className="py-2 pr-2">…this also changes</th>
                      <th className="py-2 px-2 text-right" title="P(B | A) = co_occurrences / occurrences_a">Confidence</th>
                      <th className="py-2 px-2 text-right" title="confidence / P(B) — > 1 means coupled beyond chance">Lift</th>
                      <th className="py-2 pl-2 text-right">Co-occurred</th>
                    </tr>
                  </thead>
                  <tbody>
                    {coChange.pairs.slice(0, 15).map((p, i) => {
                      const liftColor = p.lift >= 3 ? "#7C2D12" : p.lift >= 2 ? "#9A3412" : "#64748B";
                      return (
                        <tr key={i} className="border-b border-gray-50 hover:bg-indigo-50/30">
                          <td className="py-2 pr-2 font-mono text-[11px] text-td-navy">{p.object_a}</td>
                          <td className="py-2 pr-2 font-mono text-[11px] text-td-navy">
                            <ArrowRight size={10} className="inline text-indigo-400 mr-1" />
                            {p.object_b}
                          </td>
                          <td className="py-2 px-2 text-right font-mono">
                            {(p.confidence * 100).toFixed(0)}%
                          </td>
                          <td className="py-2 px-2 text-right font-mono font-bold" style={{ color: liftColor }}>
                            ×{p.lift.toFixed(2)}
                          </td>
                          <td className="py-2 pl-2 text-right text-td-gray-dark">
                            {p.co_occurrences} / {p.total_deltas}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {coChange.pairs.length > 15 && (
                <div className="text-[10px] text-td-gray-dark mt-2">
                  Showing top 15 of {coChange.pairs.length} rules by lift.
                </div>
              )}
            </div>
            </GuidedSection>
          )}
        </>
      )}

      {!scorecard && !loading && (
        <EmptyState message="Select a snapshot above to see how healthy your data warehouse is." />
      )}
    </PageShell>
  );
}
