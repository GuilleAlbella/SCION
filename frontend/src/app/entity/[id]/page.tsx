"use client";

import { use } from "react";
import Link from "next/link";
import PageShell from "@/components/layout/PageShell";
import KpiCard from "@/components/shared/KpiCard";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import { useEntity, useEntityHistory, useEntityContext } from "@/lib/hooks/useEntity";
import type { CriticalityPoint, UsagePoint } from "@/lib/api/types";
import { Database, CheckCircle, XCircle, Briefcase, Users } from "lucide-react";

// ── inline SVG sparkline ────────────────────────────────────────────────────

function Sparkline({
  points,
  color,
  width = 260,
  height = 60,
}: {
  points: number[];
  color: string;
  width?: number;
  height?: number;
}) {
  if (points.length < 2) {
    return (
      <p className="text-sm text-td-gray-dark py-6 text-center">
        Not enough data points to draw a trend.
      </p>
    );
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const pad = 4;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;

  const coords = points.map((v, i) => {
    const x = pad + (i / (points.length - 1)) * innerW;
    const y = pad + (1 - (v - min) / range) * innerH;
    return `${x},${y}`;
  });

  const areaCoords = [
    `${pad},${pad + innerH}`,
    ...coords,
    `${pad + innerW},${pad + innerH}`,
  ].join(" ");

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      aria-hidden="true"
      style={{ overflow: "visible" }}
    >
      <polygon points={areaCoords} fill={color} opacity={0.12} />
      <polyline
        points={coords.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth={2}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* endpoint dot */}
      {(() => {
        const last = coords[coords.length - 1].split(",");
        return (
          <circle
            cx={last[0]}
            cy={last[1]}
            r={3}
            fill={color}
            stroke="white"
            strokeWidth={1.5}
          />
        );
      })()}
    </svg>
  );
}

// ── criticality colour ───────────────────────────────────────────────────────

const CRIT_COLOR: Record<string, string> = {
  HIGH: "#DC2626",
  MEDIUM: "#F59E0B",
  LOW: "#16A34A",
};

function CritBadge({ level }: { level: string }) {
  const color = CRIT_COLOR[level] ?? "#6B7280";
  return (
    <span
      className="inline-block px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wide"
      style={{ backgroundColor: color + "22", color }}
    >
      {level}
    </span>
  );
}

// ── trend table ──────────────────────────────────────────────────────────────

function CriticalityTable({ rows }: { rows: CriticalityPoint[] }) {
  if (rows.length === 0) return <p className="text-sm text-td-gray-dark">No criticality data.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-td-gray-dark text-left">
            <th className="py-2 pr-4 font-medium">Snapshot</th>
            <th className="py-2 pr-4 font-medium">Level</th>
            <th className="py-2 pr-4 font-medium text-right">Score</th>
            <th className="py-2 pr-4 font-medium text-right">Usage</th>
            <th className="py-2 font-medium text-right">Graph</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.snapshot_id} className="border-b border-border/50 hover:bg-surface/50">
              <td className="py-2 pr-4 font-mono text-xs text-td-gray-dark">
                {r.snapshot_time.slice(0, 10)}
              </td>
              <td className="py-2 pr-4">
                <CritBadge level={r.criticality_level} />
              </td>
              <td className="py-2 pr-4 text-right tabular-nums">{r.combined_score.toFixed(3)}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{r.usage_score.toFixed(3)}</td>
              <td className="py-2 text-right tabular-nums">{r.graph_score.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UsageTable({ rows }: { rows: UsagePoint[] }) {
  if (rows.length === 0) return <p className="text-sm text-td-gray-dark">No usage data.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-td-gray-dark text-left">
            <th className="py-2 pr-4 font-medium">Snapshot</th>
            <th className="py-2 pr-4 font-medium text-right">Queries</th>
            <th className="py-2 font-medium text-right">Users</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.snapshot_id} className="border-b border-border/50 hover:bg-surface/50">
              <td className="py-2 pr-4 font-mono text-xs text-td-gray-dark">
                {r.snapshot_time.slice(0, 10)}
              </td>
              <td className="py-2 pr-4 text-right tabular-nums">{r.query_count.toLocaleString()}</td>
              <td className="py-2 text-right tabular-nums">{r.user_count.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── page ─────────────────────────────────────────────────────────────────────

export default function EntityDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const entityId = Number(id);

  const { data: entity, error: entityErr, isLoading: entityLoading } = useEntity(entityId);
  const { data: history, error: histErr, isLoading: histLoading } = useEntityHistory(entityId);
  const { data: context } = useEntityContext(entityId);

  const loading = entityLoading || histLoading;
  const error = entityErr || histErr;

  if (loading) {
    return (
      <PageShell title="Entity">
        <LoadingSpinner />
      </PageShell>
    );
  }

  if (error || !entity) {
    return (
      <PageShell title="Entity">
        <ErrorAlert message={(error as Error)?.message ?? "Entity not found."} />
      </PageShell>
    );
  }

  const latestCrit = history?.criticality_history.at(-1);
  const latestUsage = history?.usage_history.at(-1);

  const critScores = history?.criticality_history.map((r) => r.combined_score) ?? [];
  const queryTrend = history?.usage_history.map((r) => r.query_count) ?? [];

  return (
    <PageShell title={entity.object_name}>
      {/* breadcrumb */}
      <nav className="text-sm text-td-gray-dark mb-6">
        <Link href="/usage" className="hover:underline text-primary">
          Usage
        </Link>
        {" / "}
        <span>{entity.schema_name}</span>
        {" / "}
        <span className="font-semibold text-foreground">{entity.object_name}</span>
      </nav>

      {/* header row */}
      <div className="flex flex-wrap items-center gap-3 mb-8">
        <Database size={20} className="text-primary" />
        <h1 className="text-2xl font-bold text-foreground">{entity.object_name}</h1>
        <span className="text-sm text-td-gray-dark px-2 py-0.5 rounded bg-surface border border-border">
          {entity.entity_type}
        </span>
        {entity.is_active ? (
          <span className="flex items-center gap-1 text-xs font-medium text-green-600">
            <CheckCircle size={13} /> Active
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs font-medium text-red-500">
            <XCircle size={13} /> Inactive
          </span>
        )}
        {latestCrit && <CritBadge level={latestCrit.criticality_level} />}
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        <KpiCard
          label="Criticality score"
          value={latestCrit ? latestCrit.combined_score.toFixed(3) : "—"}
        />
        <KpiCard
          label="Queries (latest)"
          value={latestUsage ? latestUsage.query_count.toLocaleString() : "—"}
        />
        <KpiCard
          label="Changes"
          value={history?.change_count ?? 0}
        />
        <KpiCard
          label="Snapshots seen"
          value={history?.snapshots_seen ?? 0}
        />
      </div>

      {/* sparklines */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-foreground mb-4">Criticality trend</h2>
          <Sparkline points={critScores} color="#F59E0B" />
        </div>
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-foreground mb-4">Query volume trend</h2>
          <Sparkline points={queryTrend} color="#3B82F6" />
        </div>
      </div>

      {/* detail tables */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-foreground mb-4">Criticality history</h2>
          <CriticalityTable rows={history?.criticality_history ?? []} />
        </div>
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-foreground mb-4">Usage history</h2>
          <UsageTable rows={history?.usage_history ?? []} />
        </div>
      </div>

      {/* Business context panel */}
      {context && (context.owning_apps.length > 0 || context.using_teams.length > 0) && (
        <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-6">
          {context.owning_apps.length > 0 && (
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-4">
                <Briefcase size={14} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Owned by</h2>
              </div>
              <ul className="space-y-2">
                {context.owning_apps.map((app) => (
                  <li key={app.application_name} className="flex flex-col gap-0.5">
                    <span className="text-sm font-medium text-foreground">{app.application_name}</span>
                    {app.description && (
                      <span className="text-xs text-td-gray-dark">{app.description}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {context.using_teams.length > 0 && (
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-4">
                <Users size={14} className="text-primary" />
                <h2 className="text-sm font-semibold text-foreground">Used by</h2>
              </div>
              <ul className="space-y-2">
                {context.using_teams.map((team) => (
                  <li key={team.team_name} className="flex flex-col gap-0.5">
                    <span className="text-sm font-medium text-foreground">{team.team_name}</span>
                    {team.department_name && (
                      <span className="text-xs text-td-gray-dark">{team.department_name}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* metadata footer */}
      <div className="mt-8 p-4 rounded-lg bg-surface border border-border text-xs text-td-gray-dark flex flex-wrap gap-6">
        <span>Entity ID: <strong className="text-foreground">{entity.entity_id}</strong></span>
        <span>Schema: <strong className="text-foreground">{entity.schema_name}</strong></span>
        <span>First seen snapshot: <strong className="text-foreground">{entity.first_seen_snapshot_id}</strong></span>
        <span>Last seen snapshot: <strong className="text-foreground">{entity.last_seen_snapshot_id}</strong></span>
        <span>Created: <strong className="text-foreground">{entity.created_at.slice(0, 10)}</strong></span>
      </div>
    </PageShell>
  );
}
