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
} from "lucide-react";

const ENGINES = [
  { name: "snapshot", label: "Snapshot Engine", icon: Camera, key: "snapshot" },
  { name: "diff", label: "Diff Engine", icon: GitCompareArrows, key: "diff" },
  { name: "graph", label: "Impact / Graph Engine", icon: Network, key: "graph" },
  { name: "taisa", label: "TAISA Reasoning", icon: Brain, key: "taisa" },
] as const;

export default function ControlPage() {
  const { data: health, error } = useHealth();
  const [busy, setBusy] = useState<string | null>(null);

  // `busy` holds a composite key ("snapshot-restart") so we can disable all
  // buttons during an action AND highlight exactly which one is running.
  async function handleAction(engine: string, action: "stop" | "restart") {
    setBusy(`${engine}-${action}`);
    try {
      if (action === "stop") await stopEngine(engine);
      else await restartEngine(engine);
      // Revalidate /health so the StatusBadges reflect the new state.
      await mutate("health");
    } finally {
      setBusy(null);
    }
  }

  if (error) return <PageShell title="Control"><ErrorAlert message="Cannot connect to backend" /></PageShell>;
  if (!health) return <PageShell title="Control"><LoadingSpinner /></PageShell>;

  return (
    <PageShell title="Engine Control" subtitle="Start, stop, and restart SCION engines">
      {/* The Metadata API is the bedrock dependency — stopping it would crash
          the whole backend, so it's displayed read-only on purpose. */}
      {/* Database status (not controllable) */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4 flex items-center gap-3">
        <Database size={18} className="text-td-navy" />
        <span className="text-sm font-medium text-td-navy">Metadata API</span>
        <StatusBadge status={health.database} />
        <span className="text-xs text-td-gray-dark ml-auto">Not controllable (core dependency)</span>
      </div>

      {/* Controllable engines */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {ENGINES.map(({ name, label, icon: Icon, key }) => {
          const status = health[key as keyof typeof health];
          return (
            <div
              key={name}
              className="bg-white rounded-lg shadow-sm border border-gray-200 p-5"
            >
              <div className="flex items-center gap-2 mb-3">
                <Icon size={20} className="text-td-navy" />
                <span className="text-sm font-semibold text-td-navy">{label}</span>
                <StatusBadge status={status} />
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleAction(name, "stop")}
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
