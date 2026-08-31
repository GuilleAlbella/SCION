"use client";

import { useState, useEffect, useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid, Legend,
} from "recharts";
import PageShell from "@/components/layout/PageShell";
import KpiCard from "@/components/shared/KpiCard";
import DonutChart from "@/components/shared/DonutChart";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { useSelection } from "@/lib/SelectionContext";
import { getSnapshotMetrics, getGrowthRate, getVolatility } from "@/lib/api/metrics";
import type { SnapshotMetricsResponse, GrowthResponse, VolatilityResponse } from "@/lib/api/types";
import Link from "next/link";
import { Activity, TrendingUp, GitCompareArrows, ArrowRight, PieChart, ShieldCheck } from "lucide-react";
import { GuidedSection } from "@/components/shared/GuidedSection";

interface SnapshotMetricsRow extends SnapshotMetricsResponse {
  label: string;
}

export default function MetricsPage() {
  const { data: snapData } = useSnapshots();
  const { activeDiffPair } = useSelection();
  const snapshots = snapData?.snapshots ?? [];

  const [allMetrics, setAllMetrics] = useState<SnapshotMetricsRow[]>([]);
  const [growth, setGrowth] = useState<GrowthResponse | null>(null);
  const [volatility, setVolatility] = useState<VolatilityResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [compareFrom, setCompareFrom] = useState<string>("");
  const [compareTo, setCompareTo] = useState<string>("");

  // Volatility is a global metric across all snapshots — fetch once on mount.
  useEffect(() => {
    getVolatility().then(setVolatility).catch(() => {});
  }, []);

  // Dep trick: we key the effect on the JOINED list of snapshot IDs rather
  // than the `snapshots` array ref. This avoids refetching when SWR returns
  // a new array object for the same set of IDs.
  useEffect(() => {
    if (snapshots.length === 0) return;
    loadAllMetrics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapshots.map(s => s.snapshot_id).join(",")]);

  // When a diff is selected elsewhere, preload the comparison form and
  // trigger the growth-rate fetch so users see the comparison immediately.
  useEffect(() => {
    if (activeDiffPair) {
      setCompareFrom(String(activeDiffPair.snapshotFrom));
      setCompareTo(String(activeDiffPair.snapshotTo));
      loadGrowth(activeDiffPair.snapshotFrom, activeDiffPair.snapshotTo);
    }
  }, [activeDiffPair]);

  // Sequential fetch (not Promise.all) so we stay polite to the backend when
  // there are many snapshots. Individual failures are swallowed to keep the
  // trend chart usable even if one snapshot's metrics are broken.
  async function loadAllMetrics() {
    setLoading(true);
    try {
      const results: SnapshotMetricsRow[] = [];
      for (const s of snapshots) {
        try {
          const m = await getSnapshotMetrics(Number(s.snapshot_id));
          results.push({ ...m, label: `#${s.snapshot_id}` });
        } catch { /* skip */ }
      }
      setAllMetrics(results);
    } finally {
      setLoading(false);
    }
  }

  async function loadGrowth(from: number, to: number) {
    try {
      const data = await getGrowthRate(from, to);
      setGrowth(data);
    } catch {}
  }

  function handleCompare() {
    if (!compareFrom || !compareTo) return;
    loadGrowth(Number(compareFrom), Number(compareTo));
  }

  // Selected snapshot for detail view
  const selectedMetrics = allMetrics.length > 0 ? allMetrics[allMetrics.length - 1] : null;

  // Trend data for line chart
  const trendData = useMemo(() =>
    allMetrics.map((m) => ({
      name: m.label,
      schemas: m.schema_count,
      tables: m.table_count,
      views: m.view_count,
      columns: m.column_count,
      total: m.total_objects,
    })),
    [allMetrics]
  );

  // Comparison bar data
  const comparisonData = useMemo(() => {
    if (allMetrics.length < 2) return [];
    const fromM = allMetrics.find((m) => m.label === `#${compareFrom}`);
    const toM = allMetrics.find((m) => m.label === `#${compareTo}`);
    if (!fromM || !toM) return [];
    return [
      { name: "Databases", from: fromM.schema_count, to: toM.schema_count },
      { name: "Tables", from: fromM.table_count, to: toM.table_count },
      { name: "Views", from: fromM.view_count, to: toM.view_count },
      { name: "Total", from: fromM.total_objects, to: toM.total_objects },
    ];
  }, [allMetrics, compareFrom, compareTo]);

  const volColor = volatility
    ? volatility.volatility_index >= 0.15 ? "#DC2626"
      : volatility.volatility_index >= 0.05 ? "#F59E0B" : "#16A34A"
    : "#7C8185";

  const volLabel = volatility
    ? volatility.volatility_index >= 0.15 ? "Volatile"
      : volatility.volatility_index >= 0.05 ? "Moderate" : "Stable"
    : "";

  const objectBreakdown = selectedMetrics
    ? [
        { name: "Databases", value: selectedMetrics.schema_count },
        { name: "Tables", value: selectedMetrics.table_count },
        { name: "Views", value: selectedMetrics.view_count },
      ]
    : [];

  return (
    <PageShell
      title="Structural Metrics"
      subtitle="Historical trends, composition, and change detection"
    >
      {error && <ErrorAlert message={error} />}
      {loading && <LoadingSpinner />}

      {/* ═══════════════════════════════════════════════════════════
          HERO — System Volatility at a glance + latest-snapshot KPIs
          ═══════════════════════════════════════════════════════════ */}
      {(volatility || selectedMetrics) && (
        <div
          className="bg-white rounded-xl shadow-sm border-l-8 border-t border-r border-b border-gray-200 p-5 mb-6"
          style={{ borderLeftColor: volColor }}
        >
          <div className="flex items-start gap-4 mb-4">
            <div className="flex-1">
              <div className="flex items-center gap-3 mb-1">
                <Activity size={22} style={{ color: volColor }} />
                <h2 className="text-lg font-bold text-td-navy">
                  Volatility:{" "}
                  <span style={{ color: volColor }}>
                    {volatility ? `${(volatility.volatility_index * 100).toFixed(1)}% — ${volLabel}` : "—"}
                  </span>
                </h2>
              </div>
              <p className="text-xs text-td-gray-dark leading-relaxed">
                Volatility measures how often the warehouse structure changes across snapshots —
                higher means more churn. Computed across
                {" "}<strong>{volatility?.snapshot_count ?? "?"}</strong> snapshot(s).
                Below: long-term trends, latest composition, and a head-to-head comparison tool.
              </p>
            </div>
          </div>

          {volatility && (
            <div className="flex items-center gap-2 pb-4 border-b border-gray-100 mb-4">
              <div className="flex-1 h-3 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${Math.min(volatility.volatility_index * 100 * 3, 100)}%`,
                    backgroundColor: volColor,
                  }}
                />
              </div>
              <span className="text-[10px] text-td-gray-dark">
                <span className="inline-block w-2 h-2 rounded-full bg-green-500 mr-1" />0–5% Stable
                <span className="inline-block w-2 h-2 rounded-full bg-amber-500 ml-3 mr-1" />5–15% Moderate
                <span className="inline-block w-2 h-2 rounded-full bg-red-500 ml-3 mr-1" />&gt;15% Volatile
              </span>
            </div>
          )}

          {selectedMetrics && (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <KpiCard label="Databases" value={selectedMetrics.schema_count} color="#2563EB" />
              <KpiCard label="Tables" value={selectedMetrics.table_count} color="#16A34A" />
              <KpiCard label="Views" value={selectedMetrics.view_count} color="#F37440" />
              <KpiCard label="Total Objects" value={selectedMetrics.total_objects} />
            </div>
          )}
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════
          SECTION 1 · Historical trend
          ═══════════════════════════════════════════════════════════ */}
      {trendData.length >= 2 && (
        <GuidedSection
          title="1. Historical trend"
          subtitle="How the warehouse has grown (or shrunk) across snapshots"
          icon={TrendingUp}
          intro={
            <>
              One line per object class (databases / tables / views / total).
              Watch for sharp steps — they coincide with releases or ETL reorganisations.
              A steady upward slope usually indicates healthy organic growth; a sudden
              drop often flags a decommission or a failed ingest.
            </>
          }
        >
          {/* Per-category trend charts — each category gets its own Y-axis
              scale so Columns (~10M) doesn't flatten Databases (~10k) into
              an invisible line. Same approach as the comparison chart. */}
          <div className="grid grid-cols-2 md:grid-cols-2 lg:grid-cols-4 gap-3">
            {([
              { key: "total",   label: "Total",     color: "#00233C" },
              { key: "tables",  label: "Tables",    color: "#16A34A" },
              { key: "views",   label: "Views",     color: "#F37440" },
              { key: "schemas", label: "Databases", color: "#2563EB" },
            ] as const).map((cat) => (
              <div key={cat.key} className="bg-white rounded-lg shadow-sm border border-gray-200 p-3">
                <p className="text-[11px] font-medium text-td-gray-dark text-center mb-1">{cat.label}</p>
                <div style={{ width: "100%", height: 160 }}>
                  <ResponsiveContainer width="100%" height={160}>
                    <LineChart data={trendData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                      <XAxis dataKey="name" tick={{ fontSize: 9 }} />
                      <YAxis tick={{ fontSize: 9 }} width={45} />
                      <Tooltip />
                      <Line type="monotone" dataKey={cat.key} stroke={cat.color} strokeWidth={2} name={cat.label} dot={{ r: 3 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ))}
          </div>
        </GuidedSection>
      )}

      {/* ═══════════════════════════════════════════════════════════
          SECTION 2 · Current composition + Structure-change fingerprint
          ═══════════════════════════════════════════════════════════ */}
      {(objectBreakdown.length > 0 || (selectedMetrics && allMetrics.length >= 2)) && (
        <GuidedSection
          title="2. Composition & change detection"
          subtitle="What's in the warehouse now, and which snapshots actually differ"
          icon={PieChart}
          intro={
            <>
              <strong>Left:</strong> the object-type mix of the most recent snapshot —
              a quick read on whether the warehouse leans view-heavy (reporting-
              oriented) or table-heavy (raw data).{" "}
              <strong>Right:</strong> SCION generates a fingerprint of the entire warehouse structure at each snapshot. Red dots mark snapshots where the fingerprint changed vs. the previous one — a fast way to see “did anything change at all?” without loading the full diff.
            </>
          }
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {objectBreakdown.length > 0 && (
              <DonutChart
                title="Object distribution (latest snapshot)"
                data={objectBreakdown}
                colors={["#2563EB", "#16A34A", "#F37440", "#00233C"]}
              />
            )}

            {selectedMetrics && allMetrics.length >= 2 && (
              <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <ShieldCheck size={14} className="text-td-navy" />
                  <h4 className="text-sm font-semibold text-td-navy">Structure fingerprint timeline</h4>
                </div>
                <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
                  {allMetrics.map((m, i) => {
                    const isFirst = i === 0;
                    const changed = !isFirst && m.structural_hash !== allMetrics[i - 1].structural_hash;
                    return (
                      <div key={m.snapshot_id} className="flex items-center gap-3 text-xs">
                        <span className="font-semibold text-td-navy w-10 shrink-0">{m.label}</span>
                        {isFirst ? (
                          <span className="text-td-gray-dark text-[11px]">Baseline snapshot</span>
                        ) : changed ? (
                          <span className="flex items-center gap-1.5 text-red-600 font-medium">
                            <span className="w-2 h-2 rounded-full bg-red-500" />
                            Structure changed vs. {allMetrics[i - 1].label}
                          </span>
                        ) : (
                          <span className="flex items-center gap-1.5 text-green-600 font-medium">
                            <span className="w-2 h-2 rounded-full bg-green-500" />
                            Identical to {allMetrics[i - 1].label}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </GuidedSection>
      )}

      {/* ═══════════════════════════════════════════════════════════
          SECTION 3 · Head-to-head snapshot comparison
          ═══════════════════════════════════════════════════════════ */}
      <GuidedSection
        title="3. Snapshot comparison"
        subtitle="Pick two points in time and see what moved"
        icon={GitCompareArrows}
        intro={
          <>
            Bars put the two snapshots side-by-side across each object class.
            Below the chart, the <strong>growth stats</strong> breakdown answers
            “how many objects were added, removed, and net-added?” at a glance.
            The <strong>% number</strong> is total net-change divided by the
            original total — your one-sentence summary of the release.
          </>
        }
      >
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
          <div className="flex items-end gap-3 mb-4">
            <div>
              <label className="text-xs text-td-gray-dark block mb-1">From</label>
              <select value={compareFrom} onChange={(e) => setCompareFrom(e.target.value)}
                className="border border-gray-300 rounded px-3 py-1.5 text-sm">
                <option value="">Select</option>
                {snapshots.map((s) => (
                  <option key={s.snapshot_id} value={s.snapshot_id}>#{s.snapshot_id} — {s.source_system} — {new Date(s.created_at).toLocaleDateString()}</option>
                ))}
              </select>
            </div>
            <ArrowRight size={16} className="text-td-gray-dark mb-2" />
            <div>
              <label className="text-xs text-td-gray-dark block mb-1">To</label>
              <select value={compareTo} onChange={(e) => setCompareTo(e.target.value)}
                className="border border-gray-300 rounded px-3 py-1.5 text-sm">
                <option value="">Select</option>
                {snapshots.map((s) => (
                  <option key={s.snapshot_id} value={s.snapshot_id}>#{s.snapshot_id} — {s.source_system} — {new Date(s.created_at).toLocaleDateString()}</option>
                ))}
              </select>
            </div>
            <button onClick={handleCompare} disabled={!compareFrom || !compareTo}
              className="bg-td-navy text-white px-4 py-1.5 rounded text-sm font-medium hover:bg-td-navy-light disabled:opacity-50 transition-colors">
              Compare
            </button>
          </div>

          {/* Side-by-side comparison bars — one small chart per category
              instead of a single shared axis. At Transcend scale, Databases
              (~10k) and Columns (~10M) differ by 3 orders of magnitude; a
              shared Y axis flattens the smaller categories to invisible
              slivers. Each category gets its own scale instead. */}
          {comparisonData.length > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
              {comparisonData.map((row) => (
                <div key={row.name} className="border border-gray-100 rounded-lg p-2">
                  <p className="text-[11px] font-medium text-td-gray-dark text-center mb-1">{row.name}</p>
                  <div style={{ width: "100%", height: 140 }}>
                    <ResponsiveContainer width="100%" height={140}>
                      <BarChart data={[row]} barGap={2}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                        <XAxis dataKey="name" tick={false} />
                        <YAxis tick={{ fontSize: 9 }} width={40} />
                        <Tooltip />
                        <Bar dataKey="from" fill="#94A3B8" name={`#${compareFrom}`} radius={[4, 4, 0, 0]} />
                        <Bar dataKey="to" fill="#2563EB" name={`#${compareTo}`} radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              ))}
              <div className="col-span-full flex items-center justify-center gap-4 text-[11px] text-td-gray-dark">
                <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: "#94A3B8" }} />Snapshot #{compareFrom}</span>
                <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: "#2563EB" }} />Snapshot #{compareTo}</span>
              </div>
            </div>
          )}

          {/* Growth stats */}
          {growth && (
            <div className="mt-4 pt-4 border-t border-gray-100">
              <div className="flex items-center gap-4 mb-3">
                <h4 className="text-xs font-semibold text-td-navy">
                  Growth: #{growth.snapshot_from} → #{growth.snapshot_to}
                </h4>
                <span className="text-lg font-bold" style={{ color: growth.growth_percentage >= 0 ? "#16A34A" : "#DC2626" }}>
                  {growth.growth_percentage >= 0 ? "+" : ""}{growth.growth_percentage}%
                </span>
              </div>
              <div className="grid grid-cols-6 gap-3">
                <div className="bg-green-50 rounded p-2 text-center">
                  <div className="text-lg font-bold text-green-700">{growth.objects_added}</div>
                  <div className="text-[9px] text-green-600">Added</div>
                </div>
                <div className="bg-red-50 rounded p-2 text-center">
                  <div className="text-lg font-bold text-red-700">{growth.objects_removed}</div>
                  <div className="text-[9px] text-red-600">Removed</div>
                </div>
                <div className="bg-blue-50 rounded p-2 text-center">
                  <div className="text-lg font-bold" style={{ color: growth.net_change >= 0 ? "#2563EB" : "#DC2626" }}>{growth.net_change}</div>
                  <div className="text-[9px] text-blue-600">Net</div>
                </div>
                <div className="bg-green-50 rounded p-2 text-center">
                  <div className="text-lg font-bold text-green-700">{growth.schemas_added}</div>
                  <div className="text-[9px] text-green-600">Databases +</div>
                </div>
                <div className="bg-green-50 rounded p-2 text-center">
                  <div className="text-lg font-bold text-green-700">{growth.tables_added}</div>
                  <div className="text-[9px] text-green-600">Tables +</div>
                </div>
                <div className="bg-red-50 rounded p-2 text-center">
                  <div className="text-lg font-bold text-red-700">{growth.tables_removed}</div>
                  <div className="text-[9px] text-red-600">Tables -</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </GuidedSection>

      {allMetrics.length === 0 && !loading && (
        <div className="text-center py-12">
          <p className="text-sm text-td-gray-dark mb-3">No snapshots available yet. Take your first snapshot to start seeing structural metrics.</p>
          <Link href="/snapshots" className="inline-block bg-td-navy text-white text-xs font-medium px-4 py-2 rounded hover:bg-td-navy-light transition-colors">
            Go to Snapshots →
          </Link>
        </div>
      )}
    </PageShell>
  );
}
