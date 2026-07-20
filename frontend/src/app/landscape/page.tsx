"use client";

import { useState, useEffect } from "react";
import PageShell from "@/components/layout/PageShell";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { Globe2, AlertTriangle, Activity, Database, TrendingUp, ShieldAlert, CheckCircle2 } from "lucide-react";
import {
  getLandscapeSummary,
  getLandscapeRiskOverview,
  type LandscapeSummary,
  type LandscapeRiskOverview,
  type RiskObject,
} from "@/lib/api/landscape";

// ── helpers ────────────────────────────────────────────────────────

function riskColor(level: string): string {
  if (level === "HIGH") return "text-red-600";
  if (level === "MEDIUM") return "text-td-orange";
  return "text-td-downstream";
}

function riskBg(level: string): string {
  if (level === "HIGH") return "bg-red-50 border-red-200";
  if (level === "MEDIUM") return "bg-orange-50 border-orange-200";
  return "bg-green-50 border-green-200";
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = score >= 0.6 ? "bg-red-400" : score >= 0.3 ? "bg-td-orange" : "bg-td-downstream";
  return (
    <div className="flex items-center gap-2 mt-1">
      <div className="flex-1 bg-gray-200 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-td-gray-dark w-8 text-right">{pct}%</span>
    </div>
  );
}

function RiskObjectCard({ obj, rank }: { obj: RiskObject; rank: number }) {
  return (
    <li className={`rounded border p-2 ${riskBg(obj.criticality_level)}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-td-gray-dark font-mono w-4">{rank}.</span>
          <div>
            <p className="text-xs font-mono font-medium text-td-navy leading-tight">{obj.object_name}</p>
            {obj.schema_name && (
              <p className="text-[10px] text-td-gray-dark">{obj.schema_name}</p>
            )}
          </div>
        </div>
        <span className={`text-[10px] font-bold ${riskColor(obj.criticality_level)}`}>
          {obj.criticality_level}
        </span>
      </div>
      <ScoreBar score={obj.combined_score} />
    </li>
  );
}

// ── main component ─────────────────────────────────────────────────

export default function LandscapePage() {
  const [summary, setSummary] = useState<LandscapeSummary | null>(null);
  const [overview, setOverview] = useState<LandscapeRiskOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [sum, ov] = await Promise.all([
          getLandscapeSummary(10),
          getLandscapeRiskOverview(undefined, 10),
        ]);
        setSummary(sum);
        setOverview(ov);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load landscape");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  return (
    <PageShell
      title="Landscape"
      subtitle="Business-friendly portfolio view of your data estate"
      icon={Globe2}
    >
      {loading && <LoadingSpinner />}
      {error && <ErrorAlert message={error} />}

      {!loading && !error && summary && overview && (
        <div className="space-y-6">

          {/* ── KPI cards ──────────────────────────────────────────── */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard
              icon={Database}
              label="Active entities"
              value={summary.active_entity_count.toLocaleString()}
              sub={`${summary.entity_count.toLocaleString()} total ever seen`}
              color="text-td-navy"
            />
            <KpiCard
              icon={ShieldAlert}
              label="High-risk objects"
              value={summary.high_risk_count.toLocaleString()}
              sub="criticality = HIGH in latest snapshot"
              color="text-red-600"
            />
            <KpiCard
              icon={Activity}
              label="Recent changes"
              value={summary.recent_changes_count.toLocaleString()}
              sub={`in snapshot #${summary.latest_snapshot_id ?? "—"}`}
              color="text-td-orange"
            />
            <KpiCard
              icon={CheckCircle2}
              label="Risk distribution"
              value={`${overview.risk_distribution.HIGH} · ${overview.risk_distribution.MEDIUM} · ${overview.risk_distribution.LOW}`}
              sub="HIGH · MEDIUM · LOW"
              color="text-td-downstream"
            />
          </div>

          {/* ── risk distribution bar ──────────────────────────────── */}
          <section className="bg-white rounded-lg border border-gray-200 p-4">
            <h2 className="text-sm font-semibold text-td-navy mb-3">Risk distribution</h2>
            {(() => {
              const { HIGH, MEDIUM, LOW } = overview.risk_distribution;
              const total = (HIGH + MEDIUM + LOW) || 1;
              return (
                <div className="space-y-2">
                  {(
                    [
                      ["HIGH",   HIGH,   "bg-red-400"]   ,
                      ["MEDIUM", MEDIUM, "bg-td-orange"]  ,
                      ["LOW",    LOW,    "bg-td-downstream"],
                    ] as [string, number, string][]
                  ).map(([level, count, color]) => (
                    <div key={level} className="flex items-center gap-3">
                      <span className="w-14 text-xs font-medium text-right text-td-gray-dark">{level}</span>
                      <div className="flex-1 bg-gray-100 rounded-full h-3">
                        <div
                          className={`${color} h-3 rounded-full transition-all`}
                          style={{ width: `${(count / total) * 100}%` }}
                        />
                      </div>
                      <span className="w-24 text-xs text-td-gray-dark">
                        {count.toLocaleString()} ({Math.round((count / total) * 100)}%)
                      </span>
                    </div>
                  ))}
                </div>
              );
            })()}
          </section>

          {/* ── two-column lower section ───────────────────────────── */}
          <div className="grid md:grid-cols-2 gap-4">

            {/* Top critical objects */}
            <section className="bg-white rounded-lg border border-gray-200 p-4">
              <h2 className="text-sm font-semibold text-td-navy mb-3 flex items-center gap-2">
                <TrendingUp size={14} className="text-red-500" />
                Top critical objects
              </h2>
              {summary.top_risk_objects.length === 0 ? (
                <EmptyState message="No criticality data — run a diff + import first." />
              ) : (
                <ol className="space-y-2">
                  {summary.top_risk_objects.map((obj, i) => (
                    <RiskObjectCard key={obj.object_name} obj={obj} rank={i + 1} />
                  ))}
                </ol>
              )}
            </section>

            {/* At-risk: changed + high criticality */}
            <section className="bg-white rounded-lg border border-gray-200 p-4">
              <h2 className="text-sm font-semibold text-td-navy mb-3 flex items-center gap-2">
                <AlertTriangle size={14} className="text-td-orange" />
                High-risk + recently changed
              </h2>
              {overview.recently_changed_high_risk.length === 0 ? (
                <p className="text-xs text-td-gray-dark py-4 text-center">
                  No high-risk objects with recent changes — good news.
                </p>
              ) : (
                <ol className="space-y-2">
                  {overview.recently_changed_high_risk.map((obj, i) => (
                    <RiskObjectCard key={obj.object_name} obj={obj} rank={i + 1} />
                  ))}
                </ol>
              )}
            </section>
          </div>

          {/* Latest snapshot footer */}
          {summary.latest_snapshot_time && (
            <p className="text-[11px] text-td-gray-dark text-right">
              Based on snapshot #{summary.latest_snapshot_id} ·{" "}
              {new Date(summary.latest_snapshot_time).toLocaleString()}
            </p>
          )}
        </div>
      )}

      {!loading && !error && !summary && (
        <EmptyState message="No data available — import at least one snapshot first." />
      )}
    </PageShell>
  );
}

// ── KPI card sub-component ─────────────────────────────────────────

function KpiCard({
  icon: Icon,
  label,
  value,
  sub,
  color,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  sub: string;
  color: string;
}) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <div className="flex items-center gap-2 mb-1">
        <Icon size={14} className={color} />
        <span className="text-xs text-td-gray-dark">{label}</span>
      </div>
      <p className={`text-xl font-bold ${color} leading-tight`}>{value}</p>
      <p className="text-[10px] text-td-gray-dark mt-0.5">{sub}</p>
    </div>
  );
}
