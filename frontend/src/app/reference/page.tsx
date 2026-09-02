"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Building2,
  Users,
  Upload,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Database,
  Table2,
  BarChart3,
  Info,
} from "lucide-react";
import PageShell from "@/components/layout/PageShell";
import KpiCard from "@/components/shared/KpiCard";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import {
  getApplications,
  getReferenceStatus,
  getTeams,
  getUsageByApp,
  getUsageByTeam,
  uploadApplications,
  uploadUsers,
} from "@/lib/api/reference";
import type {
  AppRow,
  AppUsageResponse,
  ApplicationsResponse,
  ReferenceStatus,
  TeamRow,
  TeamUsageResponse,
  TeamsResponse,
  UserImportResponse,
  AppImportResponse,
} from "@/lib/api/types";

// ── helpers ────────────────────────────────────────────────────────────────

function fmt(n: number): string {
  return n.toLocaleString();
}

// ── import card ────────────────────────────────────────────────────────────

type UploadState = "idle" | "uploading" | "success" | "error";

interface ImportCardProps {
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  templateHint: string;
  onUpload: (file: File) => Promise<string>;
  onDone: () => void;
}

function ImportCard({ title, subtitle, icon, templateHint, onUpload, onDone }: ImportCardProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>("idle");
  const [message, setMessage] = useState("");

  const handleFile = useCallback(
    async (file: File) => {
      setState("uploading");
      setMessage("");
      try {
        const msg = await onUpload(file);
        setMessage(msg);
        setState("success");
        onDone();
      } catch (e: unknown) {
        setMessage(e instanceof Error ? e.message : "Upload failed");
        setState("error");
      }
    },
    [onUpload, onDone],
  );

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = "";
  };

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-5 flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-gray-100 flex items-center justify-center shrink-0">
          {icon}
        </div>
        <div>
          <div className="font-semibold text-gray-900 text-sm">{title}</div>
          <div className="text-xs text-td-gray-dark mt-0.5">{subtitle}</div>
        </div>
      </div>

      <div className="text-[11px] text-td-gray-dark bg-gray-50 rounded-lg px-3 py-2 font-mono leading-relaxed border border-gray-100">
        {templateHint}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".xlsx,.csv"
        className="hidden"
        onChange={handleChange}
      />

      <button
        onClick={() => inputRef.current?.click()}
        disabled={state === "uploading"}
        className="flex items-center justify-center gap-2 w-full py-2 px-4 rounded-lg text-sm font-medium
          bg-td-navy text-white hover:bg-td-navy/90 disabled:opacity-50 transition-colors"
      >
        {state === "uploading" ? (
          <Loader2 size={14} className="animate-spin" />
        ) : (
          <Upload size={14} />
        )}
        {state === "uploading" ? "Importing…" : "Upload .xlsx or .csv"}
      </button>

      {state === "success" && (
        <div className="flex items-start gap-2 text-xs text-green-700 bg-green-50 rounded-lg px-3 py-2">
          <CheckCircle2 size={13} className="mt-0.5 shrink-0" />
          {message}
        </div>
      )}
      {state === "error" && (
        <div className="flex items-start gap-2 text-xs text-red-700 bg-red-50 rounded-lg px-3 py-2">
          <AlertCircle size={13} className="mt-0.5 shrink-0" />
          {message}
        </div>
      )}
    </div>
  );
}

// ── main page ──────────────────────────────────────────────────────────────

export default function ReferencePage() {
  const [status, setStatus] = useState<ReferenceStatus | null>(null);
  const [teams, setTeams] = useState<TeamsResponse | null>(null);
  const [apps, setApps] = useState<ApplicationsResponse | null>(null);
  const [teamUsage, setTeamUsage] = useState<TeamUsageResponse | null>(null);
  const [appUsage, setAppUsage] = useState<AppUsageResponse | null>(null);
  const [tab, setTab] = useState<"org" | "apps">("org");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [s, t, a, tu, au] = await Promise.all([
        getReferenceStatus(),
        getTeams(),
        getApplications(),
        getUsageByTeam(),
        getUsageByApp(),
      ]);
      setStatus(s);
      setTeams(t);
      setApps(a);
      setTeamUsage(tu);
      setAppUsage(au);
    } catch (e: unknown) {
      setLoadError(e instanceof Error ? e.message : "Failed to load reference data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleUsersUpload = async (file: File): Promise<string> => {
    const r: UserImportResponse = await uploadUsers(file);
    const parts: string[] = [];
    if (r.departments_upserted) parts.push(`${r.departments_upserted} departments`);
    if (r.teams_upserted) parts.push(`${r.teams_upserted} teams`);
    if (r.users_upserted) parts.push(`${r.users_upserted} users`);
    if (!parts.length) parts.push("No new records (all already up to date)");
    const warn = r.warnings.length ? ` · ${r.warnings.length} warnings` : "";
    return parts.join(", ") + " imported" + warn;
  };

  const handleAppsUpload = async (file: File): Promise<string> => {
    const r: AppImportResponse = await uploadApplications(file);
    const parts: string[] = [];
    if (r.applications_upserted) parts.push(`${r.applications_upserted} applications`);
    if (r.schema_mappings_upserted) parts.push(`${r.schema_mappings_upserted} schema mappings`);
    if (r.table_mappings_upserted) parts.push(`${r.table_mappings_upserted} table mappings`);
    if (!parts.length) parts.push("No new records (all already up to date)");
    const warn = r.warnings.length ? ` · ${r.warnings.length} warnings` : "";
    return parts.join(", ") + " imported" + warn;
  };

  return (
    <PageShell
      title="Reference Data"
      subtitle="Link technical metadata to business context — teams, departments, and owning applications."
      icon={Building2}
    >
      <div className="max-w-6xl mx-auto space-y-6">

        {/* Info banner */}
        <div className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-2 flex items-start gap-2">
          <Info size={12} className="text-blue-500 shrink-0 mt-0.5" />
          <p className="text-[11px] text-td-gray-dark leading-relaxed">
            Reference Data bridges the gap between raw technical objects and the business teams that own them.
            Upload your organisation hierarchy (users → teams → departments) and application catalogue once,
            and SCION will automatically enrich every table, view and schema with ownership context — enabling
            risk scoring by business domain, filtering by team, and impact analysis scoped to a department.
            Schema and table mappings let you assign ownership at any granularity.
          </p>
        </div>

        {/* Load error */}
        {loadError && <ErrorAlert message={loadError} />}

        {/* KPI row */}
        {status && (
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
            <KpiCard label="Departments" value={status.departments} />
            <KpiCard label="Teams" value={status.teams} />
            <KpiCard label="Users" value={status.users} />
            <KpiCard label="Applications" value={status.applications} />
            <KpiCard label="Schema maps" value={status.schema_mappings} />
            <KpiCard label="Table maps" value={status.table_mappings} />
          </div>
        )}

        {/* Import cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ImportCard
            title="Organisation Hierarchy"
            subtitle="Upload a user/team/department mapping file."
            icon={<Users size={18} className="text-td-navy" />}
            templateHint={"username | display_name | email | team | department"}
            onUpload={handleUsersUpload}
            onDone={load}
          />
          <ImportCard
            title="Business Applications"
            subtitle="Upload an application-to-schema/table mapping file."
            icon={<Database size={18} className="text-td-navy" />}
            templateHint={"application_name | description | schema_name | table_name | owner_team"}
            onUpload={handleAppsUpload}
            onDone={load}
          />
        </div>

        {/* Tabs */}
        <div>
          <div className="flex gap-1 border-b border-gray-200 mb-4">
            {(
              [
                { key: "org", label: "Organisation", icon: <Users size={14} /> },
                { key: "apps", label: "Applications", icon: <Database size={14} /> },
              ] as const
            ).map(({ key, label, icon }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                  tab === key
                    ? "border-td-orange text-td-orange"
                    : "border-transparent text-td-gray-dark hover:text-gray-700"
                }`}
              >
                {icon}
                {label}
              </button>
            ))}
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 size={24} className="animate-spin text-gray-400" />
            </div>
          ) : tab === "org" ? (
            <OrgView teams={teams} teamUsage={teamUsage} />
          ) : (
            <AppsView apps={apps} appUsage={appUsage} />
          )}
        </div>
      </div>
    </PageShell>
  );
}

// ── Org tab ────────────────────────────────────────────────────────────────

function OrgView({
  teams,
  teamUsage,
}: {
  teams: TeamsResponse | null;
  teamUsage: TeamUsageResponse | null;
}) {
  if (!teams || teams.total === 0) {
    return (
      <EmptyState message="No organisation data yet. Upload a user/team mapping file to link usage data to business teams." />
    );
  }

  const usageMap = new Map(teamUsage?.teams.map((t) => [t.team_name, t]) ?? []);

  return (
    <div className="space-y-4">
      {teamUsage?.note && (
        <div className="flex items-start gap-2 text-xs text-amber-700 bg-amber-50 rounded-lg px-4 py-3">
          <Info size={14} className="mt-0.5 shrink-0" />
          {teamUsage.note}
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-gray-200 shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs text-td-gray-dark uppercase tracking-wider">
            <tr>
              <th className="px-4 py-3 text-left">Team</th>
              <th className="px-4 py-3 text-left">Department</th>
              <th className="px-4 py-3 text-right">Users</th>
              <th className="px-4 py-3 text-right">Queries</th>
              <th className="px-4 py-3 text-right">Objects accessed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {teams.teams.map((team: TeamRow) => {
              const usage = usageMap.get(team.team_name);
              return (
                <tr
                  key={team.team_id}
                  className="bg-white hover:bg-gray-50 transition-colors"
                >
                  <td className="px-4 py-3 font-medium text-gray-900">{team.team_name}</td>
                  <td className="px-4 py-3 text-td-gray-dark">
                    {team.department_name ?? <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700">{fmt(team.user_count)}</td>
                  <td className="px-4 py-3 text-right text-gray-700">
                    {usage ? fmt(usage.query_count) : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700">
                    {usage ? fmt(usage.object_count) : <span className="text-gray-300">—</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {teamUsage && teamUsage.unmapped_query_count > 0 && (
        <p className="text-xs text-td-gray-dark">
          {fmt(teamUsage.unmapped_query_count)} queries not attributed to any team.
        </p>
      )}
    </div>
  );
}

// ── Apps tab ───────────────────────────────────────────────────────────────

function AppsView({
  apps,
  appUsage,
}: {
  apps: ApplicationsResponse | null;
  appUsage: AppUsageResponse | null;
}) {
  if (!apps || apps.total === 0) {
    return (
      <EmptyState message="No application data yet. Upload an application mapping file to attribute usage to business applications." />
    );
  }

  const usageMap = new Map(appUsage?.applications.map((a) => [a.application_name, a]) ?? []);

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-lg border border-gray-200 shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs text-td-gray-dark uppercase tracking-wider">
            <tr>
              <th className="px-4 py-3 text-left">Application</th>
              <th className="px-4 py-3 text-left">Owner team</th>
              <th className="px-4 py-3 text-right">
                <span className="flex items-center justify-end gap-1">
                  <Database size={11} /> Schemas
                </span>
              </th>
              <th className="px-4 py-3 text-right">
                <span className="flex items-center justify-end gap-1">
                  <Table2 size={11} /> Tables
                </span>
              </th>
              <th className="px-4 py-3 text-right">
                <span className="flex items-center justify-end gap-1">
                  <BarChart3 size={11} /> Queries
                </span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {apps.applications.map((app: AppRow) => {
              const usage = usageMap.get(app.application_name);
              return (
                <tr
                  key={app.application_id}
                  className="bg-white hover:bg-gray-50 transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-900">{app.application_name}</div>
                    {app.description && (
                      <div className="text-xs text-td-gray-dark mt-0.5 line-clamp-1">
                        {app.description}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-td-gray-dark">
                    {app.owner_team ?? <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700">{fmt(app.schema_count)}</td>
                  <td className="px-4 py-3 text-right text-gray-700">{fmt(app.table_count)}</td>
                  <td className="px-4 py-3 text-right text-gray-700">
                    {usage ? fmt(usage.query_count) : <span className="text-gray-300">—</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {appUsage && appUsage.unmapped_query_count > 0 && (
        <p className="text-xs text-td-gray-dark">
          {fmt(appUsage.unmapped_query_count)} queries not attributed to any application.
        </p>
      )}
    </div>
  );
}
