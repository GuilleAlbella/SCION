"use client";

import { useState, useEffect } from "react";
import PageShell from "@/components/layout/PageShell";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import AnimatedCounter from "@/components/shared/AnimatedCounter";
import ObjectAutocomplete from "@/components/shared/ObjectAutocomplete";
import { useSelection } from "@/lib/SelectionContext";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { runSimulation } from "@/lib/api/simulation";
import type { SimulationResponse } from "@/lib/api/types";
import {
  FlaskConical,
  Play,
  AlertTriangle,
  CheckCircle,
  Database,
  Table2,
  Users,
  Activity,
  Settings,
  BarChart3,
  Info,
} from "lucide-react";
import { GuidedSection } from "@/components/shared/GuidedSection";

const CHANGE_TYPES = [
  { value: "TABLE_REMOVED", label: "Drop this table", danger: "HIGH" },
  { value: "TABLE_TYPE_CHANGED", label: "Convert table type (e.g. TABLE → VIEW)", danger: "HIGH" },
  { value: "COLUMN_REMOVED", label: "Drop a column from this table", danger: "HIGH" },
  { value: "COLUMN_TYPE_CHANGED", label: "Change a column data type", danger: "MEDIUM" },
  { value: "COLUMN_NULLABILITY_CHANGED", label: "Change column nullability", danger: "MEDIUM" },
];

const RISK_COLORS: Record<string, string> = {
  HIGH: "#DC2626",
  MEDIUM: "#F59E0B",
  LOW: "#16A34A",
};

export default function SimulationPage() {
  const { activeDiffPair } = useSelection();
  const { data: snapData } = useSnapshots();
  const snapshots = snapData?.snapshots ?? [];

  // Simulate against the TO-side of the active diff by default — that's the
  // "current" state the user is reasoning about. Manual select is the fallback.
  const [selectedSnap, setSelectedSnap] = useState<string>("");
  const snapshotId = activeDiffPair?.snapshotTo ?? (selectedSnap ? Number(selectedSnap) : null);

  const [selectedObject, setSelectedObject] = useState("");
  const [changeType, setChangeType] = useState(CHANGE_TYPES[0].value);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SimulationResponse | null>(null);

  // Hydrate the <select> from context, but only if the user hasn't already
  // picked something manually (hence `!selectedSnap` in the guard). Including
  // `selectedSnap` in the deps prevents the effect from overwriting manual
  // picks on every render cycle while still reacting to late context arrivals.
  useEffect(() => {
    if (activeDiffPair && !selectedSnap) {
      setSelectedSnap(String(activeDiffPair.snapshotTo));
    }
  }, [activeDiffPair, selectedSnap]);

  // Reset the object pick when the snapshot changes — a stale anchor
  // from a different snapshot would either silently 404 against the new
  // one or simulate on an object the user didn't intend.
  useEffect(() => {
    setSelectedObject("");
    setResult(null);
  }, [snapshotId]);

  async function handleSimulate() {
    if (!selectedObject || !snapshotId) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await runSimulation({
        object_identifier: selectedObject,
        change_type: changeType,
        snapshot_id: snapshotId,
      });
      setResult(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Simulation failed");
    } finally {
      setLoading(false);
    }
  }

  const riskColor = result ? RISK_COLORS[result.risk_level] ?? "#7C8185" : "#7C8185";
  const RiskIcon = result?.risk_level === "LOW" ? CheckCircle : AlertTriangle;

  return (
    <PageShell
      title="What-If Simulation"
      subtitle="Preview the impact of a change BEFORE applying it"
    >
      {/* Page intro */}
      <div className="bg-blue-50/40 border border-blue-100 rounded-lg px-3 py-2 mb-5 flex items-start gap-2">
        <Info size={12} className="text-blue-500 shrink-0 mt-0.5" />
        <p className="text-[11px] text-td-gray-dark leading-relaxed">
          Run a hypothetical scenario: <em>"What happens if I drop this column?"</em> SCION traces the dependency graph and shows you how many objects break, which queries are affected, and what the risk level would be — <strong>without touching the actual database</strong>. Use this before a migration to understand the blast radius and plan communications.
        </p>
      </div>

      {/* ═══════════════════════════════════════════════════════════
          SECTION 1 · Configure the hypothetical change
          ═══════════════════════════════════════════════════════════ */}
      <GuidedSection
        title="1. Configure the hypothetical change"
        subtitle="Read-only — nothing is changed in the database"
        icon={Settings}
        intro={
          <>
            Pick a table or view and choose the type of change you want to simulate. SCION traces the full dependency graph to compute how many objects would break, and counts affected queries and users from usage history (when available).{" "}
            <strong>Nothing is modified in the database</strong> — this is purely a preview to help you plan.
          </>
        }
      >
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
        <h3 className="text-sm font-semibold text-td-navy mb-4 flex items-center gap-2">
          <FlaskConical size={14} className="text-purple-600" />
          Configure the hypothetical change
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          {/* Snapshot */}
          <div>
            <label className="text-xs text-td-gray-dark block mb-1">Against snapshot</label>
            <select
              value={selectedSnap}
              onChange={(e) => setSelectedSnap(e.target.value)}
              className="border border-gray-300 rounded px-3 py-2 text-sm w-full"
            >
              <option value="">Select...</option>
              {snapshots.map((s) => (
                <option key={s.snapshot_id} value={s.snapshot_id}>
                  #{s.snapshot_id} — {s.source_system} — {new Date(s.created_at).toLocaleDateString()}
                </option>
              ))}
            </select>
          </div>

          {/* Object — server-backed autocomplete restricted to TABLE/VIEW.
              Replaces the legacy two-input "filter + native select" combo
              that used to load the full snapshot graph (337k+ nodes on
              Transcend) into the dropdown. The autocomplete debounces,
              hits /objects/search?source=graph&object_types=TABLE,VIEW,
              and only renders matches as the user types. */}
          <div>
            <label className="text-xs text-td-gray-dark block mb-1">Target object</label>
            <ObjectAutocomplete
              value={selectedObject}
              onChange={setSelectedObject}
              snapshotId={snapshotId ?? undefined}
              source="graph"
              objectTypes="TABLE,VIEW,UNKNOWN"
              placeholder={snapshotId ? "Type a table or view name..." : "Pick a snapshot first"}
              disabled={!snapshotId}
            />
          </div>

          {/* Change type */}
          <div>
            <label className="text-xs text-td-gray-dark block mb-1">Hypothetical change</label>
            <select
              value={changeType}
              onChange={(e) => setChangeType(e.target.value)}
              className="border border-gray-300 rounded px-3 py-2 text-sm w-full"
            >
              {CHANGE_TYPES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <button
          onClick={handleSimulate}
          disabled={loading || !selectedObject || !snapshotId}
          className="flex items-center gap-2 bg-gradient-to-r from-purple-600 to-purple-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold hover:from-purple-700 hover:to-purple-800 disabled:opacity-50 transition-all shadow-sm"
        >
          <Play size={14} />
          {loading ? "Simulating..." : "Run Simulation"}
        </button>
      </div>
      </GuidedSection>

      {error && <ErrorAlert message={error} />}
      {loading && <LoadingSpinner />}

      {result && (
        <GuidedSection
          title="2. Simulation result"
          subtitle="What would happen if you applied this change today"
          icon={BarChart3}
          intro={
            <>
              The big coloured card is SCION&apos;s overall verdict + a human-readable
              recommendation. Below, four numbers tell you <strong>who feels it</strong>:
              direct and indirect dependents from the lineage graph, plus (if usage data is
              loaded) the estimated queries and distinct users that touch the affected objects.
              The table at the bottom is the full ripple list, sorted by depth — hand it
              to the owner teams before release.
            </>
          }
        >
          {/* ──── Result banner ──── Big risk badge + prose recommendation.
              Border colour is driven by the backend risk_level so the visual
              impact scales with severity. */}
          <div
            className="bg-white rounded-xl shadow-sm border-2 p-6 mb-6"
            style={{ borderColor: riskColor }}
          >
            <div className="flex items-start gap-4">
              <div
                className="w-14 h-14 rounded-2xl flex items-center justify-center shrink-0"
                style={{ backgroundColor: `${riskColor}15` }}
              >
                <RiskIcon size={28} style={{ color: riskColor }} />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="px-3 py-0.5 rounded-full text-xs font-bold text-white"
                    style={{ backgroundColor: riskColor }}
                  >
                    {result.risk_level} RISK
                  </span>
                  {result.is_breaking && (
                    <span className="bg-red-600 text-white px-3 py-0.5 rounded-full text-xs font-bold">
                      BREAKING
                    </span>
                  )}
                  <span className="text-xs text-td-gray-dark">Severity: {result.severity}</span>
                </div>
                <div className="text-sm text-td-navy font-mono mb-2">
                  <span className="text-td-gray-dark">Hypothetical change on:</span>{" "}
                  <strong>{result.object_identifier}</strong>
                </div>
                <p className="text-sm text-gray-700 leading-relaxed">
                  {result.recommendation}
                </p>
              </div>
            </div>
          </div>

          {/* KPI grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
              <AnimatedCounter
                value={result.direct_impacts.length}
                className="text-3xl font-bold text-red-600"
              />
              <div className="text-[11px] text-td-gray-dark uppercase tracking-wider mt-1">
                Direct dependents
              </div>
            </div>
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
              <AnimatedCounter
                value={result.indirect_impacts.length}
                className="text-3xl font-bold text-amber-600"
              />
              <div className="text-[11px] text-td-gray-dark uppercase tracking-wider mt-1">
                Indirect dependents
              </div>
            </div>
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
              <AnimatedCounter
                value={result.queries_affected}
                className="text-3xl font-bold text-td-orange"
              />
              <div className="text-[11px] text-td-gray-dark uppercase tracking-wider mt-1 flex items-center justify-center gap-1">
                <Activity size={10} />
                Queries affected
              </div>
            </div>
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
              <AnimatedCounter
                value={result.users_affected}
                className="text-3xl font-bold text-td-object"
              />
              <div className="text-[11px] text-td-gray-dark uppercase tracking-wider mt-1 flex items-center justify-center gap-1">
                <Users size={10} />
                Users affected
              </div>
            </div>
          </div>

          {/* Affected objects table */}
          {(result.direct_impacts.length + result.indirect_impacts.length) > 0 ? (
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
              <div className="px-5 py-3 border-b border-gray-200 flex items-center gap-2">
                <Table2 size={14} className="text-td-navy" />
                <h3 className="text-sm font-semibold text-td-navy">
                  Objects that would be affected ({result.direct_impacts.length + result.indirect_impacts.length})
                </h3>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 text-left border-b border-gray-200">
                    <th className="px-4 py-2 font-medium text-xs text-td-gray-dark">Object</th>
                    <th className="px-4 py-2 font-medium text-xs text-td-gray-dark">Impact</th>
                    <th className="px-4 py-2 font-medium text-xs text-td-gray-dark">Depth</th>
                  </tr>
                </thead>
                <tbody>
                  {[...result.direct_impacts, ...result.indirect_impacts].map((imp, i) => (
                    <tr key={i} className="border-t border-gray-100 hover:bg-gray-50">
                      <td className="px-4 py-2 font-mono text-xs">
                        <Database size={10} className="inline mr-1 text-td-gray-dark" />
                        {imp.object_name}
                      </td>
                      <td className="px-4 py-2">
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded-full text-white ${
                            imp.impact_level === "DOWNSTREAM" ? "bg-red-600" : "bg-blue-600"
                          }`}
                        >
                          {imp.impact_level}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-xs text-td-gray-dark">
                        {imp.depth === 1 ? "Direct (1 hop)" : `${imp.depth} hops away`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-center gap-3">
              <CheckCircle size={18} className="text-green-600" />
              <span className="text-sm text-green-800">
                No downstream objects detected. This change is isolated.
              </span>
            </div>
          )}
        </GuidedSection>
      )}

      {!result && !loading && (
        <EmptyState message="Configure a hypothetical change above and click 'Run Simulation' to see its impact." />
      )}
    </PageShell>
  );
}
