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
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5 flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-td-navy/10 dark:bg-white/10 flex items-center justify-center shrink-0">
          {icon}
        </div>
        <div>
          <div className="font-semibold text-gray-900 dark:text-white text-sm">{title}</div>
          <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{subtitle}</div>
        </div>
      </div>

      <div className="text-[11px] text-gray-400 dark:text-gray-500 bg-gray-50 dark:bg-gray-900 rounded-lg px-3 py-2 font-mono leading-relaxed">
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
        <div className="flex items-start gap-2 text-xs text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-900/20 rounded-lg px-3 py-2">
          <CheckCircle2 size={13} className="mt-0.5 shrink-0" />
          {message}
        </div>
      )}
      {state === "error" && (
        <div className="flex items-start gap-2 text-xs text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">
          <AlertCircle size={13} className="mt-0.5 shrink-0" />
          {message}
        </div>
      )}
    </div>
  );
}

// ── stat chip ──────────────────────────────────────────────────────────────

function StatChip({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col items-center bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl px-5 py-3">
      <span className="text-2xl font-bold text-td-navy dark:text-white">{fmt(value)}</span>
      <span className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{label}</span>
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
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <Building2 size={22} className="text-td-navy dark:text-white" />
          Reference Data
        </h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Link technical metadata to business context — teams, departments, and owning applications.
        </p>
      </div>

      {/* Load error — shown when the initial fetch fails (e.g. backend starting up) */}
      {loadError && (
        <div className="flex items-start gap-2 text-sm text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl px-4 py-3">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <span>{loadError}</span>
        </div>
      )}

      {/* KPI row */}
      {status && (
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
          <StatChip label="Departments" value={status.departments} />
          <StatChip label="Teams" value={status.teams} />
          <StatChip label="Users" value={status.users} />
          <StatChip label="Applications" value={status.applications} />
          <StatChip label="Schema maps" value={status.schema_mappings} />
          <StatChip label="Table maps" value={status.table_mappings} />
        </div>
      )}

      {/* Import cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ImportCard
          title="Organisation Hierarchy"
          subtitle="Upload a user/team/department mapping file."
          icon={<Users size={18} className="text-td-navy dark:text-white" />}
          templateHint={"username | display_name | email | team | department"}
          onUpload={handleUsersUpload}
          onDone={load}
        />
        <ImportCard
          title="Business Applications"
          subtitle="Upload an application-to-schema/table mapping file."
          icon={<Database size={18} className="text-td-navy dark:text-white" />}
          templateHint={"application_name | description | schema_name | table_name | owner_team"}
          onUpload={handleAppsUpload}
          onDone={load}
        />
      </div>

      {/* Tabs: Org view / App view */}
      <div>
        <div className="flex gap-1 border-b border-gray-200 dark:border-gray-700 mb-4">
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
                  : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
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
      <EmptyState
        icon={<Users size={28} className="text-gray-300 dark:text-gray-600" />}
        title="No organisation data yet"
        description="Upload a user/team mapping file to link usage data to business teams."
      />
    );
  }

  const usageMap = new Map(teamUsage?.teams.map((t) => [t.team_name, t]) ?? []);

  return (
    <div className="space-y-4">
      {/* Usage notice */}
      {teamUsage?.note && (
        <div className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 rounded-lg px-4 py-3">
          <Info size={14} className="mt-0.5 shrink-0" />
          {teamUsage.note}
        </div>
      )}

      {/* Teams table */}
      <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-800 text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">
            <tr>
              <th className="px-4 py-3 text-left">Team</th>
              <th className="px-4 py-3 text-left">Department</th>
              <th className="px-4 py-3 text-right">Users</th>
              <th className="px-4 py-3 text-right">Queries</th>
              <th className="px-4 py-3 text-right">Objects accessed</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {teams.teams.map((team: TeamRow) => {
              const usage = usageMap.get(team.team_name);
              return (
                <tr
                  key={team.team_id}
                  className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  <td className="px-4 py-3 font-medium text-gray-900 dark:text-white">
                    {team.team_name}
                  </td>
                  <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
                    {team.department_name ?? <span className="text-gray-300 dark:text-gray-600">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700 dark:text-gray-300">
                    {fmt(team.user_count)}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700 dark:text-gray-300">
                    {usage ? fmt(usage.query_count) : <span className="text-gray-300 dark:text-gray-600">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700 dark:text-gray-300">
                    {usage ? fmt(usage.object_count) : <span className="text-gray-300 dark:text-gray-600">—</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {teamUsage && teamUsage.unmapped_query_count > 0 && (
        <p className="text-xs text-gray-400 dark:text-gray-500">
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
      <EmptyState
        icon={<Database size={28} className="text-gray-300 dark:text-gray-600" />}
        title="No application data yet"
        description="Upload an application mapping file to attribute usage to business applications."
      />
    );
  }

  const usageMap = new Map(appUsage?.applications.map((a) => [a.application_name, a]) ?? []);

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-800 text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">
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
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {apps.applications.map((app: AppRow) => {
              const usage = usageMap.get(app.application_name);
              return (
                <tr
                  key={app.application_id}
                  className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-900 dark:text-white">
                      {app.application_name}
                    </div>
                    {app.description && (
                      <div className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 line-clamp-1">
                        {app.description}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
                    {app.owner_team ?? <span className="text-gray-300 dark:text-gray-600">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700 dark:text-gray-300">
                    {fmt(app.schema_count)}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700 dark:text-gray-300">
                    {fmt(app.table_count)}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700 dark:text-gray-300">
                    {usage ? fmt(usage.query_count) : <span className="text-gray-300 dark:text-gray-600">—</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {appUsage && appUsage.unmapped_query_count > 0 && (
        <p className="text-xs text-gray-400 dark:text-gray-500">
          {fmt(appUsage.unmapped_query_count)} queries not attributed to any application.
        </p>
      )}
    </div>
  );
}

// ── empty state ────────────────────────────────────────────────────────────

function EmptyState({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
      {icon}
      <div className="font-medium text-gray-600 dark:text-gray-300">{title}</div>
      <div className="text-sm text-gray-400 dark:text-gray-500 max-w-sm">{description}</div>
    </div>
  );
}
