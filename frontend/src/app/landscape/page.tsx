"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import PageShell from "@/components/layout/PageShell";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import {
  LayoutGrid,
  Activity,
  Database,
  ChevronRight,
  X,
  TrendingUp,
  ShieldAlert,
  Layers,
  ExternalLink,
  Search,
  Flame,
} from "lucide-react";
import {
  getLandscapeSummary,
  getLandscapeSchemas,
  getLandscapeRiskOverview,
  getSchemaObjects,
  type LandscapeSummary,
  type LandscapeRiskOverview,
  type SchemaRiskSummary,
  type RiskObject,
} from "@/lib/api/landscape";
import { globalSearch } from "@/lib/api/search";
import type { SearchResponse } from "@/lib/api/types";

// ── helpers ────────────────────────────────────────────────────────

function riskBadge(level: string): string {
  if (level === "HIGH") return "bg-red-100 text-red-700 border border-red-200";
  if (level === "MEDIUM") return "bg-orange-100 text-orange-700 border border-orange-200";
  return "bg-green-100 text-green-700 border border-green-200";
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color =
    score >= 0.6 ? "bg-red-400" : score >= 0.3 ? "bg-td-orange" : "bg-td-downstream";
  return (
    <div className="flex items-center gap-2 mt-1">
      <div className="flex-1 bg-gray-200 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-td-gray-dark w-8 text-right tabular-nums">{pct}%</span>
    </div>
  );
}

// ── Level-1: schema card ───────────────────────────────────────────

function healthStatus(schema: SchemaRiskSummary): {
  label: string;
  dotColor: string;
  textColor: string;
} {
  if (schema.high_count > 0)
    return { label: "Needs attention", dotColor: "bg-red-500", textColor: "text-red-600" };
  if (schema.medium_count > 0)
    return { label: "Monitoring", dotColor: "bg-td-orange", textColor: "text-orange-600" };
  return { label: "Healthy", dotColor: "bg-td-downstream", textColor: "text-green-600" };
}

function SchemaCard({
  schema,
  selected,
  hasRecentChange,
  onClick,
}: {
  schema: SchemaRiskSummary;
  selected: boolean;
  hasRecentChange: boolean;
  onClick: () => void;
}) {
  const total = schema.total_objects || 1;
  const highPct = (schema.high_count / total) * 100;
  const medPct = (schema.medium_count / total) * 100;
  const lowPct = (schema.low_count / total) * 100;
  const health = healthStatus(schema);

  return (
    <button
      onClick={onClick}
      className={`w-full text-left rounded-lg border p-3 transition-all hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-td-orange ${
        selected
          ? "border-td-orange bg-orange-50 ring-1 ring-td-orange"
          : "border-gray-200 bg-white hover:border-td-orange/50"
      }`}
    >
      {/* Schema name row */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <Layers
            size={13}
            className={selected ? "text-td-orange shrink-0" : "text-td-gray-dark shrink-0"}
          />
          <span className="text-xs font-semibold text-td-navy font-mono truncate">
            {schema.schema_name}
          </span>
        </div>
        <ChevronRight
          size={12}
          className={`text-td-gray-dark transition-transform duration-200 shrink-0 ml-1 ${
            selected ? "rotate-90" : ""
          }`}
        />
      </div>

      {/* Health status row */}
      <div className="flex items-center gap-1.5 mb-2">
        <span className={`w-2 h-2 rounded-full shrink-0 ${health.dotColor}`} />
        <span className={`text-[10px] font-medium ${health.textColor}`}>{health.label}</span>
        {hasRecentChange && (
          <span className="ml-auto text-[9px] font-semibold text-red-600 bg-red-50 border border-red-200 px-1 py-0.5 rounded">
            changed
          </span>
        )}
      </div>

      {/* Mini risk bar */}
      <div className="h-1.5 rounded-full overflow-hidden flex bg-gray-100">
        <div className="bg-red-400 transition-all" style={{ width: `${highPct}%` }} />
        <div className="bg-td-orange transition-all" style={{ width: `${medPct}%` }} />
        <div className="bg-td-downstream transition-all" style={{ width: `${lowPct}%` }} />
      </div>

      {/* Object count */}
      <p className="text-[10px] text-td-gray-dark mt-1.5 tabular-nums">
        {schema.total_objects.toLocaleString()} object{schema.total_objects !== 1 ? "s" : ""}
        {schema.high_count > 0 && (
          <span className="text-red-600 font-medium">
            {" · "}{schema.high_count} critical
          </span>
        )}
      </p>
    </button>
  );
}

// ── Level-2: schema detail drawer ────────────────────────────────

function SchemaDrawer({
  schema,
  objects,
  loading,
  snapshotId,
  onClose,
}: {
  schema: SchemaRiskSummary | null;
  objects: RiskObject[];
  loading: boolean;
  snapshotId: number | null;
  onClose: () => void;
}) {
  if (!schema) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-30 bg-black/10"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer panel */}
      <aside className="fixed inset-y-0 right-0 w-96 bg-white shadow-2xl border-l border-gray-200 flex flex-col z-40">
        {/* Header */}
        <div className="px-4 py-3 border-b border-gray-100 bg-td-navy text-white flex items-center justify-between shrink-0">
          <div>
            <p className="text-[10px] text-white/50 uppercase tracking-wider">Schema</p>
            <p className="text-sm font-semibold font-mono">{schema.schema_name}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded hover:bg-white/10 transition-colors"
            aria-label="Close"
          >
            <X size={15} />
          </button>
        </div>

        {/* Schema risk summary bar */}
        <div className="px-4 py-2 border-b border-gray-100 bg-gray-50 flex items-center gap-4 shrink-0">
          <div className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-red-400 shrink-0" />
            <span className="text-[10px] text-td-gray-dark tabular-nums">
              {schema.high_count} HIGH
            </span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-td-orange shrink-0" />
            <span className="text-[10px] text-td-gray-dark tabular-nums">
              {schema.medium_count} MED
            </span>
          </div>
          <div className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-td-downstream shrink-0" />
            <span className="text-[10px] text-td-gray-dark tabular-nums">
              {schema.low_count} LOW
            </span>
          </div>
          <span className="ml-auto text-[10px] text-td-gray-dark tabular-nums">
            avg {Math.round(schema.avg_score * 100)}%
          </span>
        </div>

        {/* Level-2 object list */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <LoadingSpinner />
            </div>
          ) : objects.length === 0 ? (
            <EmptyState message="No criticality data for this schema." />
          ) : (
            <ul className="divide-y divide-gray-100">
              {objects.map((obj) => {
                const tableName =
                  obj.object_name.includes(".")
                    ? obj.object_name.split(".").slice(1).join(".")
                    : obj.object_name;
                return (
                  <li key={obj.object_name} className="px-4 py-2.5 hover:bg-gray-50 group">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-mono text-td-navy truncate">{tableName}</span>
                      <div className="flex items-center gap-1.5 shrink-0">
                        <span
                          className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${riskBadge(obj.criticality_level)}`}
                        >
                          {obj.criticality_level}
                        </span>
                        {/* Level-3: link to Changes page filtered by object */}
                        <Link
                          href={`/changes?object=${encodeURIComponent(obj.object_name)}`}
                          className="opacity-0 group-hover:opacity-100 transition-opacity"
                          title="View changes for this object"
                        >
                          <ExternalLink size={11} className="text-td-orange" />
                        </Link>
                      </div>
                    </div>
                    <ScoreBar score={obj.combined_score} />
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* Footer — view changes link */}
        <div className="px-4 py-2.5 border-t border-gray-100 shrink-0">
          <Link
            href={`/changes?schema=${encodeURIComponent(schema.schema_name)}`}
            className="flex items-center gap-1.5 text-xs text-td-orange hover:underline"
          >
            <Activity size={12} />
            View all changes in {schema.schema_name}
          </Link>
        </div>
      </aside>
    </>
  );
}

// ── KPI card ──────────────────────────────────────────────────────

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
      <p className={`text-xl font-bold ${color} leading-tight tabular-nums`}>{value}</p>
      <p className="text-[10px] text-td-gray-dark mt-0.5">{sub}</p>
    </div>
  );
}

// ── §2.15.b: Executive Summary Dashboard ─────────────────────────

function ExecutiveSummaryDashboard({
  summary,
  riskOverview,
  globalDist,
}: {
  summary: LandscapeSummary;
  riskOverview: LandscapeRiskOverview | null;
  globalDist: { HIGH: number; MEDIUM: number; LOW: number };
}) {
  const total = (globalDist.HIGH + globalDist.MEDIUM + globalDist.LOW) || 1;
  const healthPct = Math.round(
    ((globalDist.LOW + globalDist.MEDIUM * 0.5) / total) * 100,
  );
  const healthLabel =
    healthPct >= 80 ? "Stable" : healthPct >= 50 ? "At risk" : "Critical";
  const healthColor =
    healthPct >= 80
      ? "text-td-downstream"
      : healthPct >= 50
        ? "text-td-orange"
        : "text-red-600";
  const healthBorderBg =
    healthPct >= 80
      ? "border-green-200 bg-green-50"
      : healthPct >= 50
        ? "border-orange-200 bg-orange-50"
        : "border-red-200 bg-red-50";

  const changedHighRisk = riskOverview?.recently_changed_high_risk ?? [];
  const dist: [string, number, string][] = [
    ["HIGH", globalDist.HIGH, "bg-red-400"],
    ["MEDIUM", globalDist.MEDIUM, "bg-td-orange"],
    ["LOW", globalDist.LOW, "bg-td-downstream"],
  ];

  return (
    <section className="bg-white rounded-lg border border-gray-200 p-4 space-y-4">
      {/* Health score + risk distribution */}
      <div className="flex items-stretch gap-4">
        <div
          className={`rounded-lg border p-3 flex flex-col items-center justify-center min-w-[110px] ${healthBorderBg}`}
        >
          <p className="text-[9px] font-semibold text-td-gray-dark uppercase tracking-widest mb-1">
            Portfolio health
          </p>
          <p
            className={`text-4xl font-bold tabular-nums leading-none ${healthColor}`}
          >
            {healthPct}%
          </p>
          <p className={`text-[10px] font-semibold mt-1 ${healthColor}`}>
            {healthLabel}
          </p>
        </div>

        <div className="flex-1">
          <p className="text-[10px] font-semibold text-td-gray-dark uppercase tracking-wide mb-2">
            Risk distribution
          </p>
          <div className="space-y-1.5">
            {dist.map(([level, count, color]) => (
              <div key={level} className="flex items-center gap-3">
                <span className="w-14 text-xs font-medium text-right text-td-gray-dark">
                  {level}
                </span>
                <div className="flex-1 bg-gray-100 rounded-full h-3">
                  <div
                    className={`${color} h-3 rounded-full transition-all`}
                    style={{ width: `${(count / total) * 100}%` }}
                  />
                </div>
                <span className="w-24 text-xs text-td-gray-dark tabular-nums">
                  {count.toLocaleString()} ({Math.round((count / total) * 100)}
                  %)
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Changes affecting applications widget */}
      {(summary.applications_count > 0 || summary.teams_count > 0) && (
        <div className="flex items-center gap-2 bg-gray-50 rounded border border-gray-200 px-3 py-2">
          <Activity size={12} className="text-td-orange shrink-0" />
          <p className="text-xs text-td-navy">
            <span className="font-semibold">
              {summary.recent_changes_count.toLocaleString()} recent change
              {summary.recent_changes_count !== 1 ? "s" : ""}
            </span>{" "}
            in the latest snapshot, affecting your{" "}
            {summary.applications_count > 0 && (
              <span className="font-semibold">
                {summary.applications_count.toLocaleString()} registered
                application
                {summary.applications_count !== 1 ? "s" : ""}
              </span>
            )}
            {summary.applications_count > 0 && summary.teams_count > 0 &&
              " and "}
            {summary.teams_count > 0 && (
              <span className="font-semibold">
                {summary.teams_count.toLocaleString()} team
                {summary.teams_count !== 1 ? "s" : ""}
              </span>
            )}
          </p>
        </div>
      )}

      {/* Attention required */}
      {changedHighRisk.length > 0 && (
        <div className="border-t border-gray-100 pt-3">
          <div className="flex items-center gap-2 mb-2">
            <Flame size={12} className="text-red-600" />
            <h2 className="text-xs font-semibold text-red-800">
              Attention required
            </h2>
            <span className="text-[10px] text-red-600">
              {changedHighRisk.length} high-risk object
              {changedHighRisk.length !== 1 ? "s" : ""} changed this snapshot
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {changedHighRisk.map((obj) => {
              const bare = obj.object_name.includes(".")
                ? obj.object_name.split(".").slice(1).join(".")
                : obj.object_name;
              return (
                <Link
                  key={obj.object_name}
                  href={`/changes?object=${encodeURIComponent(obj.object_name)}`}
                  className="flex items-center gap-1.5 bg-white border border-red-200 rounded px-2 py-1 text-xs hover:bg-red-50 hover:border-red-400 transition-colors"
                >
                  <span className="font-mono text-td-navy">{bare}</span>
                  <span className="text-[9px] text-red-600 font-semibold tabular-nums">
                    {Math.round(obj.combined_score * 100)}%
                  </span>
                  <ExternalLink size={10} className="text-red-400" />
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

// ── main page ─────────────────────────────────────────────────────

export default function LandscapePage() {
  const [summary, setSummary] = useState<LandscapeSummary | null>(null);
  const [schemas, setSchemas] = useState<SchemaRiskSummary[]>([]);
  const [riskOverview, setRiskOverview] = useState<LandscapeRiskOverview | null>(null);
  const [selectedSchema, setSelectedSchema] = useState<SchemaRiskSummary | null>(null);
  const [schemaObjects, setSchemaObjects] = useState<RiskObject[]>([]);
  const [loadingMain, setLoadingMain] = useState(true);
  const [loadingObjects, setLoadingObjects] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Cross-source search state
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResponse | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    async function load() {
      setLoadingMain(true);
      setError(null);
      try {
        const [sum, schs, overview] = await Promise.all([
          getLandscapeSummary(10),
          getLandscapeSchemas(),
          getLandscapeRiskOverview().catch(() => null),
        ]);
        setSummary(sum);
        setSchemas(schs);
        setRiskOverview(overview);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load landscape");
      } finally {
        setLoadingMain(false);
      }
    }
    load();
  }, []);

  // Debounced cross-source search
  useEffect(() => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    searchTimerRef.current = setTimeout(async () => {
      setSearchLoading(true);
      try {
        const res = await globalSearch(searchQuery.trim());
        setSearchResults(res);
      } catch {
        setSearchResults(null);
      } finally {
        setSearchLoading(false);
      }
    }, 350);
  }, [searchQuery]);

  const handleSchemaClick = useCallback(
    async (schema: SchemaRiskSummary) => {
      if (selectedSchema?.schema_name === schema.schema_name) {
        setSelectedSchema(null);
        setSchemaObjects([]);
        return;
      }
      setSelectedSchema(schema);
      setSchemaObjects([]);
      setLoadingObjects(true);
      try {
        const objs = await getSchemaObjects(
          schema.schema_name,
          summary?.latest_snapshot_id ?? undefined,
        );
        setSchemaObjects(objs);
      } catch {
        setSchemaObjects([]);
      } finally {
        setLoadingObjects(false);
      }
    },
    [selectedSchema, summary],
  );

  // Aggregate risk distribution from schemas
  const globalDist = schemas.reduce(
    (acc, s) => ({
      HIGH: acc.HIGH + s.high_count,
      MEDIUM: acc.MEDIUM + s.medium_count,
      LOW: acc.LOW + s.low_count,
    }),
    { HIGH: 0, MEDIUM: 0, LOW: 0 },
  );

  // Schemas that have recently changed high-risk objects
  const recentlyChangedSchemas = new Set(
    (riskOverview?.recently_changed_high_risk ?? []).map((o) => o.schema_name),
  );

  // Sort schemas by business impact: HIGH desc → MEDIUM desc → total desc
  const sortedSchemas = [...schemas].sort(
    (a, b) =>
      b.high_count - a.high_count ||
      b.medium_count - a.medium_count ||
      b.total_objects - a.total_objects,
  );

  const needAttentionCount = schemas.filter((s) => s.high_count > 0).length;
  const recentChangeCount = recentlyChangedSchemas.size;

  return (
    <>
      <PageShell
        title="Landscape"
        subtitle="Business-friendly portfolio view of your data estate"
        icon={LayoutGrid}
      >
        {loadingMain && <LoadingSpinner />}
        {error && <ErrorAlert message={error} />}

        {!loadingMain && !error && summary && (
          <div
            className={`space-y-5 transition-all duration-300 ${selectedSchema ? "mr-96" : ""}`}
          >
            {/* ── §2.15.a: Cross-source search ─────────────────────── */}
            <div className="relative">
              <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-3 py-2.5 focus-within:border-td-orange focus-within:ring-1 focus-within:ring-td-orange transition-all">
                <Search size={14} className="text-td-gray-dark shrink-0" />
                <input
                  className="flex-1 text-sm outline-none bg-transparent placeholder-td-gray-dark"
                  placeholder="Search objects across all schemas…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                {searchLoading && (
                  <span className="text-[10px] text-td-gray-dark animate-pulse">searching…</span>
                )}
                {searchQuery && !searchLoading && (
                  <button
                    onClick={() => { setSearchQuery(""); setSearchResults(null); }}
                    className="text-td-gray-dark hover:text-foreground transition-colors"
                    aria-label="Clear search"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>

              {/* Search results dropdown */}
              {searchResults && searchResults.results.length > 0 && (
                <div className="absolute top-full left-0 right-0 z-20 bg-white border border-gray-200 rounded-lg shadow-lg mt-1 max-h-72 overflow-y-auto">
                  {searchResults.results.map((r, i) => (
                    <Link
                      key={`${r.object_name}-${i}`}
                      href={`/changes?object=${encodeURIComponent(r.object_name)}`}
                      onClick={() => { setSearchQuery(""); setSearchResults(null); }}
                      className="flex items-center justify-between px-3 py-2 hover:bg-gray-50 border-b border-gray-50 last:border-0"
                    >
                      <div className="min-w-0">
                        <span className="text-xs font-mono text-td-navy truncate block">{r.object_name}</span>
                        <span className="text-[10px] text-td-gray-dark">{r.schema_name}</span>
                      </div>
                      <span className="text-[9px] uppercase font-medium text-td-gray-dark ml-3 shrink-0">{r.object_type}</span>
                    </Link>
                  ))}
                </div>
              )}
              {searchResults && searchResults.results.length === 0 && searchQuery && (
                <div className="absolute top-full left-0 right-0 z-20 bg-white border border-gray-200 rounded-lg shadow-sm mt-1 px-3 py-2.5">
                  <p className="text-xs text-td-gray-dark">No objects found for &ldquo;{searchQuery}&rdquo;</p>
                </div>
              )}
            </div>

            {/* ── Level 0: KPI cards ──────────────────────────────── */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KpiCard
                icon={Database}
                label="Active objects"
                value={summary.active_entity_count.toLocaleString()}
                sub={`${summary.entity_count.toLocaleString()} total`}
                color="text-td-navy"
              />
              <KpiCard
                icon={ShieldAlert}
                label="High-risk"
                value={summary.high_risk_count.toLocaleString()}
                sub="latest snapshot"
                color="text-red-600"
              />
              <KpiCard
                icon={Activity}
                label="Recent changes"
                value={summary.recent_changes_count.toLocaleString()}
                sub={`snapshot #${summary.latest_snapshot_id ?? "—"}`}
                color="text-td-orange"
              />
              <KpiCard
                icon={Layers}
                label="Schemas"
                value={schemas.length.toLocaleString()}
                sub="in latest snapshot"
                color="text-td-downstream"
              />
            </div>

            {/* ── §2.15.b: Executive Summary Dashboard ─────────────── */}
            {(globalDist.HIGH + globalDist.MEDIUM + globalDist.LOW) > 0 && (
              <ExecutiveSummaryDashboard
                summary={summary}
                riskOverview={riskOverview}
                globalDist={globalDist}
              />
            )}

            {/* ── Level 1: schema grid ─────────────────────────────── */}
            <section>
              <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <TrendingUp size={14} className="text-td-navy" />
                  <h2 className="text-sm font-semibold text-td-navy">Your data estate</h2>
                </div>
                <p className="text-[10px] text-td-gray-dark">
                  {schemas.length} schema{schemas.length !== 1 ? "s" : ""}
                  {needAttentionCount > 0 && (
                    <span className="text-red-600 font-medium">
                      {" · "}{needAttentionCount} need{needAttentionCount === 1 ? "s" : ""} attention
                    </span>
                  )}
                  {recentChangeCount > 0 && (
                    <span className="text-orange-600 font-medium">
                      {" · "}{recentChangeCount} changed recently
                    </span>
                  )}
                  <span className="text-td-gray-dark"> — click to drill down</span>
                </p>
              </div>

              {schemas.length === 0 ? (
                <EmptyState message="No schema data — import a snapshot with criticality scores first." />
              ) : (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                  {sortedSchemas.map((s) => (
                    <SchemaCard
                      key={s.schema_name}
                      schema={s}
                      selected={selectedSchema?.schema_name === s.schema_name}
                      hasRecentChange={recentlyChangedSchemas.has(s.schema_name)}
                      onClick={() => handleSchemaClick(s)}
                    />
                  ))}
                </div>
              )}
            </section>

            {/* Snapshot footer */}
            {summary.latest_snapshot_time && (
              <p className="text-[11px] text-td-gray-dark text-right">
                Based on snapshot #{summary.latest_snapshot_id} ·{" "}
                {new Date(summary.latest_snapshot_time).toLocaleString()}
              </p>
            )}
          </div>
        )}

        {!loadingMain && !error && !summary && (
          <EmptyState message="No data available — import at least one snapshot first." />
        )}
      </PageShell>

      {/* Level-2 drawer — outside PageShell, covers full viewport height */}
      <SchemaDrawer
        schema={selectedSchema}
        objects={schemaObjects}
        loading={loadingObjects}
        snapshotId={summary?.latest_snapshot_id ?? null}
        onClose={() => {
          setSelectedSchema(null);
          setSchemaObjects([]);
        }}
      />
    </>
  );
}
