"use client";

import { useState } from "react";
import { mutate } from "swr";
import PageShell from "@/components/layout/PageShell";
import StatusBadge from "@/components/shared/StatusBadge";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import { useHealth } from "@/lib/hooks/useHealth";
import { stopEngine, restartEngine } from "@/lib/api/control";
import {
  Database,
  Camera,
  GitCompareArrows,
  Network,
  Brain,
  Square,
  RotateCcw,
  Info,
  AlertTriangle,
} from "lucide-react";

const ENGINES = [
  {
    name: "snapshot",
    label: "Snapshot Engine",
    icon: Camera,
    key: "snapshot",
    description: "Reads the Teradata catalog and creates a point-in-time snapshot of all tables, views, columns, and their definitions.",
  },
  {
    name: "diff",
    label: "Diff Engine",
    icon: GitCompareArrows,
    key: "diff",
    description: "Compares two consecutive snapshots and detects structural changes: added/removed columns, type changes, dropped objects.",
  },
  {
    name: "graph",
    label: "Impact & Graph Engine",
    icon: Network,
    key: "graph",
    description: "Builds the lineage graph from SQL dependencies and computes metrics like fragility, hub nodes, and blast radius.",
  },
  {
    name: "taisa",
    label: "AI Reasoning Engine",
    icon: Brain,
    key: "taisa",
    description: "Analyzes detected changes using an AI model to classify risk, explain impact in plain language, and generate recommendations.",
  },
] as const;

export default function ControlPage() {
  const { data: health, error } = useHealth();
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmStop, setConfirmStop] = useState<string | null>(null);

  async function handleAction(engine: string, action: "stop" | "restart") {
    setBusy(`${engine}-${action}`);
    try {
      if (action === "stop") await stopEngine(engine);
      else await restartEngine(engine);
      await mutate("health");
    } finally {
      setBusy(null);
    }
  }

  if (error) return <PageShell title="Control"><ErrorAlert message="Cannot connect to backend" /></PageShell>;
  if (!health) return <PageShell title="Control"><LoadingSpinner /></PageShell>;

  return (
    <PageShell title="Engine Control" subtitle="Start, stop, and restart SCION engines">
      {/* Page intro */}
      <div className="bg-blue-50/40 border border-blue-100 rounded-lg px-3 py-2 mb-5 flex items-start gap-2">
        <Info size={12} className="text-blue-500 shrink-0 mt-0.5" />
        <p className="text-[11px] text-td-gray-dark leading-relaxed">
          This page is for <strong>SCION administrators</strong>. Each engine runs independently in the background — you can stop or restart one without affecting the others. Stopping an engine pauses its processing; restarting it resumes from where it left off. The <strong>Metadata API</strong> is the shared database connection and cannot be stopped from here.
        </p>
      </div>

      {/* Confirmation dialog overlay */}
      {confirmStop && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
          <div className="bg-white rounded-xl shadow-xl border border-gray-200 p-6 max-w-sm w-full mx-4">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle size={18} className="text-red-500" />
              <h3 className="text-sm font-bold text-td-navy">Stop engine?</h3>
            </div>
            <p className="text-xs text-td-gray-dark mb-4">
              Stopping <strong>{ENGINES.find((e) => e.name === confirmStop)?.label ?? confirmStop}</strong> will pause its processing until manually restarted. Any in-progress operation will be interrupted.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setConfirmStop(null)}
                className="px-3 py-1.5 text-xs font-medium text-td-gray-dark border border-gray-200 rounded hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => { handleAction(confirmStop, "stop"); setConfirmStop(null); }}
                className="px-3 py-1.5 text-xs font-medium text-white bg-red-600 rounded hover:bg-red-700 transition-colors"
              >
                Stop engine
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Metadata API (read-only) */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4 flex items-center gap-3">
        <Database size={18} className="text-td-navy" />
        <div className="flex-1">
          <span className="text-sm font-medium text-td-navy">Metadata API</span>
          <p className="text-[11px] text-td-gray-dark">Shared database connection used by all engines. Read-only — required by all other engines.</p>
        </div>
        <StatusBadge status={health.database} />
      </div>

      {/* Controllable engines */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {ENGINES.map(({ name, label, icon: Icon, key, description }) => {
          const status = health[key as keyof typeof health];
          return (
            <div
              key={name}
              className="bg-white rounded-lg shadow-sm border border-gray-200 p-5"
            >
              <div className="flex items-center gap-2 mb-1.5">
                <Icon size={20} className="text-td-navy" />
                <span className="text-sm font-semibold text-td-navy">{label}</span>
                <StatusBadge status={status} />
              </div>
              <p className="text-[11px] text-td-gray-dark mb-3 leading-relaxed">{description}</p>
              <div className="flex gap-2">
                <button
                  onClick={() => setConfirmStop(name)}
                  disabled={busy !== null}
                  className="flex items-center gap-1.5 px-3 py-1.5 border border-red-300 text-red-600 rounded text-xs font-medium hover:bg-red-50 disabled:opacity-50 transition-colors"
                >
                  <Square size={12} />
                  {busy === `${name}-stop` ? "Stopping..." : "Stop"}
                </button>
                <button
                  onClick={() => handleAction(name, "restart")}
                  disabled={busy !== null}
                  className="flex items-center gap-1.5 px-3 py-1.5 border border-green-300 text-green-600 rounded text-xs font-medium hover:bg-green-50 disabled:opacity-50 transition-colors"
                >
                  <RotateCcw size={12} />
                  {busy === `${name}-restart` ? "Restarting..." : "Restart"}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </PageShell>
  );
}
