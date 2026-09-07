"use client";

import PageShell from "@/components/layout/PageShell";
import KpiCard from "@/components/shared/KpiCard";
import StatusBadge from "@/components/shared/StatusBadge";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import { useHealth } from "@/lib/hooks/useHealth";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { useChanges } from "@/lib/hooks/useChanges";
import { useSelection } from "@/lib/SelectionContext";
import Link from "next/link";
import AnimatedCounter from "@/components/shared/AnimatedCounter";
import { changeTypeLabel } from "@/lib/terminology";
import { APP_VERSION, APP_STAGE } from "@/lib/constants";
import {
  Database,
  Camera,
  GitCompareArrows,
  Network,
  Brain,
  ArrowRight,
  Shield,
  TrendingUp,
  Flame,
  ShieldCheck,
  Target,
  ChevronRight,
  Zap,
  AlertTriangle,
  Bell,
  Activity,
} from "lucide-react";

const ENGINE_META = [
  { key: "database", label: "Metadata API", icon: Database, color: "#2563EB" },
  { key: "snapshot", label: "Snapshot Engine", icon: Camera, color: "#16A34A" },
  { key: "diff", label: "Diff Engine", icon: GitCompareArrows, color: "#F37440" },
  { key: "graph", label: "Impact & Graph Engine", icon: Network, color: "#0D7377" },
  { key: "taisa", label: "AI Reasoning Engine", icon: Brain, color: "#7C3AED" },
] as const;

const QUICK_ACTIONS = [
  { href: "/snapshots", label: "Capture Snapshot", desc: "Take a new metadata snapshot", icon: Camera, color: "#2563EB" },
  { href: "/changes", label: "Analyze Changes", desc: "Compare snapshots & detect changes", icon: GitCompareArrows, color: "#F37440" },
  { href: "/impact", label: "Object Change Analysis", desc: "Upstream & downstream impact of each structural change", icon: Target, color: "#DC2626" },
  { href: "/intelligence", label: "Governance", desc: "Health scorecard & domain risk", icon: ShieldCheck, color: "#16A34A" },
];

export default function DashboardPage() {
  // Three SWR-backed hooks run in parallel. `activeDiffPair` comes from the
  // cross-page SelectionContext — if the user ran a diff elsewhere, we show
  // a banner linking back to Impact analysis.
  const { data: health, error: healthErr } = useHealth();
  const { data: snapshots } = useSnapshots();
  const { data: changes } = useChanges();
  const { activeDiffPair } = useSelection();

  // Hard-fail on backend unreachable; most of the dashboard is meaningless
  // without /health. Other hooks tolerate partial failure.
  if (healthErr) return <PageShell title="Dashboard"><ErrorAlert message="Cannot connect to backend API" /></PageShell>;
  if (!health) return <PageShell title="Dashboard"><LoadingSpinner /></PageShell>;

  const snapCount = snapshots?.snapshots.length ?? 0;
  const changeCount = changes?.changes.length ?? 0;

  return (
    <PageShell title="Dashboard" subtitle="SCION — Structural Change Intelligence & Observability Node">
      {/* ──── Hero banner ──── Welcome + running snapshot count + active diff link */}
      <div className="bg-gradient-to-r from-td-navy to-td-navy-light rounded-xl p-6 mb-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-light tracking-wide">
              Welcome to <span className="font-bold text-td-orange">Project SCION</span>
            </h2>
            <p className="text-white/60 text-sm mt-1 max-w-lg">
              Monitor structural changes across your data warehouse, assess impact,
              and get AI-powered risk recommendations — all in one place.
            </p>
            <span className="inline-block mt-2 bg-td-orange/20 text-td-orange text-xs font-bold px-2.5 py-0.5 rounded-full tracking-wide">
              {APP_STAGE ? `${APP_STAGE} ${APP_VERSION}` : APP_VERSION}
            </span>
          </div>
          <div className="text-right">
            <AnimatedCounter value={snapCount} className="text-3xl font-bold text-white" />
            <div className="text-white/50 text-xs">snapshots captured</div>
          </div>
        </div>

        {/* Active diff context */}
        {activeDiffPair && (
          <div className="mt-4 pt-4 border-t border-white/10 flex items-center gap-3">
            <Shield size={16} className="text-td-orange" />
            <span className="text-sm text-white/70">
              Active analysis: <span className="text-white font-medium">Snapshot #{activeDiffPair.snapshotFrom} → #{activeDiffPair.snapshotTo}</span>
            </span>
            <Link href="/impact" className="ml-auto text-xs bg-white/10 hover:bg-white/20 px-3 py-1 rounded-full transition-colors">
              View Impact →
            </Link>
          </div>
        )}
      </div>

      {/* ──── KPI Row ──── System/snapshot/change/TAISA at-a-glance cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-8 h-8 rounded-lg bg-green-100 flex items-center justify-center">
              <Shield size={16} className="text-green-600" />
            </div>
            <span className="text-xs text-td-gray-dark uppercase tracking-wider">System</span>
          </div>
          <div className="text-xl font-bold text-td-navy capitalize">{health.status}</div>
        </div>
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-8 h-8 rounded-lg bg-blue-100 flex items-center justify-center">
              <Camera size={16} className="text-blue-600" />
            </div>
            <span className="text-xs text-td-gray-dark uppercase tracking-wider">Snapshots</span>
          </div>
          <AnimatedCounter value={snapCount} className="text-xl font-bold" style={{ color: "#2563EB" }} />
        </div>
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-8 h-8 rounded-lg bg-orange-100 flex items-center justify-center">
              <GitCompareArrows size={16} className="text-orange-600" />
            </div>
            <span className="text-xs text-td-gray-dark uppercase tracking-wider">Changes</span>
          </div>
          <AnimatedCounter value={changeCount} className="text-xl font-bold" style={{ color: "#F37440" }} />
        </div>
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-8 h-8 rounded-lg bg-purple-100 flex items-center justify-center">
              <Brain size={16} className="text-purple-600" />
            </div>
            <span className="text-xs text-td-gray-dark uppercase tracking-wider">AI Engine</span>
          </div>
          <div className="text-xl font-bold text-td-navy"><StatusBadge status={health.taisa} /></div>
        </div>
      </div>

      {/* Quick Actions */}
      <h2 className="text-sm font-semibold text-td-navy mb-3">Quick Actions</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {QUICK_ACTIONS.map(({ href, label, desc, icon: Icon, color }) => (
          <Link
            key={href}
            href={href}
            className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 hover:shadow-md hover:border-gray-300 transition-all group"
          >
            <div className="w-10 h-10 rounded-lg flex items-center justify-center mb-3"
              style={{ backgroundColor: `${color}15` }}>
              <Icon size={20} style={{ color }} />
            </div>
            <div className="text-sm font-semibold text-td-navy group-hover:text-td-orange transition-colors">
              {label}
            </div>
            <div className="text-[11px] text-td-gray-dark mt-0.5">{desc}</div>
          </Link>
        ))}
      </div>

      {/* Alert Ticker + Recent Changes */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {/* Breaking changes alert */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-7 h-7 rounded-lg bg-red-100 flex items-center justify-center">
              <AlertTriangle size={14} className="text-red-600" />
            </div>
            <h3 className="text-xs font-semibold text-td-navy uppercase tracking-wider">Breaking Changes</h3>
          </div>
          {changes?.changes.filter((c) => c.is_breaking).length ? (
            <div className="space-y-2 max-h-32 overflow-y-auto">
              {changes.changes
                .filter((c) => c.is_breaking)
                .slice(0, 5)
                .map((c) => (
                  <div key={c.change_id} className="flex items-center gap-2 text-xs">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />
                    <span className="font-mono text-td-gray-dark truncate">{c.object_name}</span>
                    <span
                      className="bg-red-100 text-red-700 px-1.5 py-0.5 rounded text-[10px] font-medium ml-auto shrink-0"
                      title={c.change_type}
                    >
                      {changeTypeLabel(c.change_type)}
                    </span>
                  </div>
                ))}
            </div>
          ) : (
            <p className="text-xs text-td-gray-dark">No breaking changes detected</p>
          )}
        </div>

        {/* Recent activity */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-7 h-7 rounded-lg bg-blue-100 flex items-center justify-center">
              <Activity size={14} className="text-blue-600" />
            </div>
            <h3 className="text-xs font-semibold text-td-navy uppercase tracking-wider">Recent Activity</h3>
          </div>
          {changes?.changes.length ? (
            <div className="space-y-2 max-h-32 overflow-y-auto">
              {changes.changes.slice(0, 6).map((c) => (
                <div key={c.change_id} className="flex items-center gap-2 text-xs">
                  <span
                    className="w-1.5 h-1.5 rounded-full shrink-0"
                    style={{ backgroundColor: c.severity === "HIGH" ? "#DC2626" : c.severity === "MEDIUM" ? "#F59E0B" : "#16A34A" }}
                  />
                  <span className="text-td-gray-dark truncate flex-1" title={c.change_type}>
                    {changeTypeLabel(c.change_type)}
                  </span>
                  <span className="font-mono text-td-gray-dark truncate max-w-[150px]">{c.object_name.split(".").pop()}</span>
                  <span className="text-[10px] text-td-gray-dark/50 shrink-0">
                    {new Date(c.created_at).toLocaleDateString()}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-td-gray-dark">No recent changes</p>
          )}
        </div>
      </div>

      {/* ──── Engine Status ──── Per-engine health pulled from /health. Keys must match ENGINE_META[].key */}
      <h2 className="text-sm font-semibold text-td-navy mb-3">Engine Status</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
        {ENGINE_META.map(({ key, label, icon: Icon, color }) => (
          <div
            key={key}
            className="bg-white rounded-xl shadow-sm border border-gray-200 p-4"
          >
            <div className="flex items-center gap-2 mb-2">
              <div className="w-7 h-7 rounded-md flex items-center justify-center"
                style={{ backgroundColor: `${color}15` }}>
                <Icon size={14} style={{ color }} />
              </div>
              <span className="text-xs font-medium text-td-navy">{label}</span>
            </div>
            <StatusBadge status={health[key as keyof typeof health]} />
          </div>
        ))}
      </div>

      {/* ──── Processing Pipeline ──── Visual 5-stage flow (Ingest → Snapshot → Diff → Impact → TAISA).
          The step number and colour are shared with the engine cards above so users map icon ↔ engine. */}
      <div className="bg-gradient-to-br from-slate-900 via-td-navy to-slate-900 rounded-xl shadow-lg p-6 text-white overflow-hidden relative">
        {/* Background decoration */}
        <div className="absolute inset-0 opacity-5">
          <div className="absolute top-0 left-1/4 w-64 h-64 bg-td-orange rounded-full blur-3xl" />
          <div className="absolute bottom-0 right-1/4 w-64 h-64 bg-blue-500 rounded-full blur-3xl" />
        </div>

        <div className="relative">
          <div className="flex items-center gap-2 mb-5">
            <Zap size={16} className="text-td-orange" />
            <h2 className="text-sm font-semibold tracking-wide">Processing Pipeline</h2>
            <span className="text-[10px] text-white/40 ml-1">Real-time engine status</span>
          </div>

          <div className="grid grid-cols-5 gap-3">
            {[
              {
                key: "database" as const,
                label: "Ingest",
                desc: "Multi-engine metadata extraction",
                icon: Database,
                color: "#2563EB",
                step: 1,
              },
              {
                key: "snapshot" as const,
                label: "Snapshot",
                desc: "Point-in-time structure capture",
                icon: Camera,
                color: "#16A34A",
                step: 2,
              },
              {
                key: "diff" as const,
                label: "Diff",
                desc: "Detect structural changes between snapshots",
                icon: GitCompareArrows,
                color: "#F37440",
                step: 3,
              },
              {
                key: "graph" as const,
                label: "Impact",
                desc: "Graph traversal & impact spread",
                icon: Network,
                color: "#DC2626",
                step: 4,
              },
              {
                key: "taisa" as const,
                label: "AI Engine",
                desc: "AI risk classification",
                icon: Brain,
                color: "#A855F7",
                step: 5,
              },
            ].map(({ key, label, desc, icon: Icon, color, step }, i) => {
              const status = health[key];
              const isReady = status === "ready" || status === "mock_ready" || status === "real_ready";
              return (
                <div key={key} className="relative">
                  {/* Connector arrow */}
                  {i < 4 && (
                    <div className="absolute -right-3 top-1/2 -translate-y-1/2 z-10">
                      <ChevronRight size={18} className="text-white/20" />
                    </div>
                  )}

                  <div
                    className="rounded-xl p-4 border transition-all hover:scale-[1.03] hover:shadow-lg cursor-default h-full"
                    style={{
                      backgroundColor: `${color}12`,
                      borderColor: `${color}30`,
                    }}
                  >
                    {/* Step number + status */}
                    <div className="flex items-center justify-between mb-3">
                      <span
                        className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold text-white"
                        style={{ backgroundColor: color }}
                      >
                        {step}
                      </span>
                      <span className="flex items-center gap-1">
                        <span
                          className="w-2 h-2 rounded-full animate-pulse"
                          style={{ backgroundColor: isReady ? "#22C55E" : "#EF4444" }}
                        />
                        <span className={`text-[9px] font-medium ${isReady ? "text-green-400" : "text-red-400"}`}>
                          {isReady ? "LIVE" : "OFF"}
                        </span>
                      </span>
                    </div>

                    {/* Icon */}
                    <div
                      className="w-10 h-10 rounded-lg flex items-center justify-center mb-3"
                      style={{ backgroundColor: `${color}25` }}
                    >
                      <Icon size={20} style={{ color }} />
                    </div>

                    {/* Text */}
                    <div className="text-sm font-semibold text-white mb-0.5">{label}</div>
                    <div className="text-[10px] text-white/50 leading-relaxed">{desc}</div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Flow line */}
          <div className="mt-4 flex items-center gap-2 justify-center">
            <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/20 to-transparent" />
            <span className="text-[10px] text-white/30 px-2">
              Each stage runs independently with real-time status monitoring
            </span>
            <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/20 to-transparent" />
          </div>
        </div>
      </div>
    </PageShell>
  );
}
