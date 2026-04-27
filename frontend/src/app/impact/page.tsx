"use client";

import { useState, useMemo } from "react";
import PageShell from "@/components/layout/PageShell";
import DonutChart from "@/components/shared/DonutChart";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { useSelection } from "@/lib/SelectionContext";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { runBatchImpact } from "@/lib/api/impact";
import type { BatchImpactResponse } from "@/lib/api/types";
import { IMPACT_COLORS } from "@/lib/constants";
import { Play, Zap, Shield, Layers, FileText, Download, GitBranch, Database, ListTree, Boxes } from "lucide-react";
import { useToast } from "@/components/shared/ToastProvider";
import Confetti from "@/components/shared/Confetti";
import InfoTooltip from "@/components/shared/InfoTooltip";
import { GuidedSection, HeroStat, BigStat } from "@/components/shared/GuidedSection";
import { changeTypeLabel } from "@/lib/terminology";

const SEVERITY_COLORS: Record<string, string> = {
  HIGH: "#DC2626",
  MEDIUM: "#F59E0B",
  LOW: "#16A34A",
};

const RISK_COLORS: Record<string, string> = {
  HIGH: "#DC2626",
  MEDIUM: "#F59E0B",
  LOW: "#16A34A",
};

export default function ImpactPage() {
  const { activeDiffPair, setCachedDiffDetails, setCachedImpactResults } = useSelection();
  const { data: snapData } = useSnapshots();

  const [manualFrom, setManualFrom] = useState("");
  const [manualTo, setManualTo] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BatchImpactResponse | null>(null);
  const { toast } = useToast();
  const [showConfetti, setShowConfetti] = useState(false);

  // Prefer the cross-page diff selection; fall back to manual dropdown inputs
  // so the page is still usable if the user lands here directly.
  const from = activeDiffPair?.snapshotFrom ?? (manualFrom ? Number(manualFrom) : null);
  const to = activeDiffPair?.snapshotTo ?? (manualTo ? Number(manualTo) : null);
  const snapshots = snapData?.snapshots ?? [];

  async function handleAnalyze() {
    if (from == null || to == null) return;
    setLoading(true);
    setError(null);

    try {
      const data = await runBatchImpact(from, to);
      setResult(data);
      toast(`Impact analysis complete: ${data.summary.overall_risk} risk`, data.summary.overall_risk === "HIGH" ? "error" : "success");
      // Celebrate when the whole diff comes back LOW — the Confetti component
      // self-ends after its animation; the 100ms reset just flips the flag so
      // a follow-up LOW result can re-trigger it.
      if (data.summary.overall_risk === "LOW") {
        setShowConfetti(true);
        setTimeout(() => setShowConfetti(false), 100);
      }

      // Push a lightweight projection into SelectionContext so Lineage can
      // highlight "changed in this diff" without re-fetching impact details.
      // Only metadata is cached; per-node graph lists are left empty.
      setCachedImpactResults(
        data.changes.map((c) => ({
          changeId: c.change_id,
          objectIdentifier: c.object_identifier,
          changeType: c.change_type,
          severity: c.severity,
          isBreaking: c.is_breaking,
          impact: {
            change_id: c.change_id,
            direct_impact: [],
            indirect_impact: [],
            summary: { direct_count: c.direct_count, indirect_count: c.indirect_count },
          },
        }))
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  // ──── Donut aggregations ────
  // Each useMemo re-runs only when `result` changes — we group changes by
  // severity, change_type, schema, and impact direction. The `detail` field
  // on each slice is what the DonutChart shows on hover (top-3 objects).
  // Aggregate for donut charts — with detail text for tooltips
  const bySeverity = useMemo(() => {
    if (!result) return [];
    const groups = new Map<string, { count: number; objects: string[] }>();
    for (const c of result.changes) {
      const g = groups.get(c.severity) ?? { count: 0, objects: [] };
      g.count++;
      g.objects.push(c.object_identifier);
      groups.set(c.severity, g);
    }
    return Array.from(groups, ([name, g]) => ({
      name,
      value: g.count,
      detail: g.objects.slice(0, 3).join(", ") + (g.objects.length > 3 ? ` +${g.objects.length - 3} more` : ""),
    }));
  }, [result]);

  const byChangeType = useMemo(() => {
    if (!result) return [];
    const groups = new Map<string, { count: number; objects: string[] }>();
    for (const c of result.changes) {
      const label = changeTypeLabel(c.change_type);
      const g = groups.get(label) ?? { count: 0, objects: [] };
      g.count++;
      g.objects.push(c.object_identifier.split(".").pop() ?? c.object_identifier);
      groups.set(label, g);
    }
    return Array.from(groups, ([name, g]) => ({
      name,
      value: g.count,
      detail: `Affected: ${g.objects.join(", ")}`,
    }));
  }, [result]);

  const bySchema = useMemo(() => {
    if (!result) return [];
    const groups = new Map<string, { count: number; breaking: number; objects: string[] }>();
    for (const c of result.changes) {
      const schema = c.object_identifier.split(".")[0] || "unknown";
      const g = groups.get(schema) ?? { count: 0, breaking: 0, objects: [] };
      g.count++;
      if (c.is_breaking) g.breaking++;
      g.objects.push(c.object_identifier.split(".").slice(1).join("."));
      groups.set(schema, g);
    }
    return Array.from(groups, ([name, g]) => ({
      name,
      value: g.count,
      detail: `${g.breaking} breaking · Objects: ${g.objects.slice(0, 3).join(", ")}`,
    }));
  }, [result]);

  const byImpactDirection = useMemo(() => {
    if (!result) return [];
    const withImpact = result.changes.filter(c => c.direct_count > 0 || c.indirect_count > 0);
    const withoutImpact = result.changes.filter(c => c.direct_count === 0 && c.indirect_count === 0);
    const data = [];
    if (withImpact.length > 0)
      data.push({ name: "Has downstream impact", value: withImpact.length, detail: `${withImpact.reduce((s, c) => s + c.direct_count + c.indirect_count, 0)} total impact nodes` });
    if (withoutImpact.length > 0)
      data.push({ name: "No graph impact", value: withoutImpact.length, detail: "Column-level or isolated changes" });
    return data;
  }, [result]);

  return (
    <PageShell
      title="Summary Impact Analysis"
      subtitle="Full-diff impact assessment — how far each change ripples"
    >
      <Confetti active={showConfetti} />

      {/* ──── Selector ──── Either shows the active diff pair (coming from
          Changes page via context) or a manual snapshot picker. */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        {activeDiffPair ? (
          <div className="flex items-center gap-4">
            <Zap size={18} className="text-td-orange" />
            <span className="text-sm text-td-navy">
              Diff: <strong>#{activeDiffPair.snapshotFrom}</strong> →{" "}
              <strong>#{activeDiffPair.snapshotTo}</strong>
              {result && <span className="text-td-downstream ml-2">✓ analyzed</span>}
            </span>
            <button onClick={handleAnalyze} disabled={loading}
              className="ml-auto flex items-center gap-2 bg-td-navy text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-td-navy-light disabled:opacity-50 transition-colors">
              <Play size={16} />
              {loading ? "Analyzing..." : result ? "Re-analyze" : "Analyze Full Diff"}
            </button>
          </div>
        ) : (
          <div className="flex items-end gap-3">
            <div>
              <label className="text-xs text-td-gray-dark block mb-1">From</label>
              <select value={manualFrom} onChange={(e) => setManualFrom(e.target.value)}
                className="border border-gray-300 rounded px-3 py-1.5 text-sm">
                <option value="">Select</option>
                {snapshots.map((s) => (
                  <option key={s.snapshot_id} value={s.snapshot_id}>#{s.snapshot_id}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-td-gray-dark block mb-1">To</label>
              <select value={manualTo} onChange={(e) => setManualTo(e.target.value)}
                className="border border-gray-300 rounded px-3 py-1.5 text-sm">
                <option value="">Select</option>
                {snapshots.map((s) => (
                  <option key={s.snapshot_id} value={s.snapshot_id}>#{s.snapshot_id}</option>
                ))}
              </select>
            </div>
            <button onClick={handleAnalyze} disabled={loading || !manualFrom || !manualTo}
              className="flex items-center gap-2 bg-td-navy text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-td-navy-light disabled:opacity-50 transition-colors">
              <Play size={16} />
              {loading ? "Analyzing..." : "Analyze Full Diff"}
            </button>
          </div>
        )}
      </div>

      {error && <ErrorAlert message={error} />}
      {loading && <LoadingSpinner />}

      {result && (
        <>
          {/* ═══════════════════════════════════════════════════════════
              SECTION 1 · HERO
              One cohesive hero that fuses what was previously TWO rows
              (Blast Radius banner + KPI row) plus the floating "criteria"
              blurb, plus the export buttons. The overall risk color is
              the dominant visual cue — everything else hangs off it.
              ═══════════════════════════════════════════════════════════ */}
          <div
            className="bg-white rounded-xl shadow-sm border-l-8 border-t border-r border-b border-gray-200 p-5 mb-6"
            style={{ borderLeftColor: RISK_COLORS[result.summary.overall_risk] ?? "#7C8185" }}
          >
            <div className="flex items-start gap-4 mb-4">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-1">
                  <Shield size={22} style={{ color: RISK_COLORS[result.summary.overall_risk] ?? "#7C8185" }} />
                  <h2 className="text-lg font-bold text-td-navy">
                    Overall risk:{" "}
                    <span style={{ color: RISK_COLORS[result.summary.overall_risk] ?? "#7C8185" }}>
                      {result.summary.overall_risk}
                    </span>
                  </h2>
                </div>
                <p className="text-xs text-td-gray-dark leading-relaxed">
                  Analyzing <strong>{result.changes_analyzed}</strong> structural change(s)
                  from snapshot <strong>#{result.snapshot_from}</strong> → <strong>#{result.snapshot_to}</strong>.
                  This classification blends severity, breaking-count, impact spread and usage weight.
                  Read the sections below for each dimension.
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={() => {
                    const f = from;
                    const t = to;
                    if (f != null && t != null) {
                      const url = `${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1"}/report/${f}/${t}`;
                      window.open(url, "_blank");
                    }
                  }}
                  className="flex items-center gap-1 bg-td-orange text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-td-orange/90 transition-colors"
                >
                  <FileText size={14} />
                  Report (HTML)
                </button>
                <a
                  href={`${process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1"}/export/impact/${result.snapshot_from}/${result.snapshot_to}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 bg-green-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-green-700 transition-colors"
                >
                  <Download size={14} />
                  CSV
                </a>
              </div>
            </div>

            {/* Top-line KPIs — 4 numbers only, de-duplicated. Each has a
                tooltip so viewers can verify what they mean without
                cross-referencing the legend. */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t border-gray-100">
              <HeroStat
                value={result.changes_analyzed}
                label="Changes"
                tooltip="Structural diffs between the two snapshots (adds/removes/type changes)."
                color="#00233C"
              />
              <HeroStat
                value={result.summary.breaking_count}
                label="Breaking"
                tooltip="Changes that will break downstream consumers (DROP TABLE, incompatible type changes, etc.)."
                color="#DC2626"
              />
              <HeroStat
                value={result.blast_radius.total_impacted_nodes}
                label="Impacted objects"
                tooltip="Distinct downstream objects (tables/views/procs) that transitively feel at least one change."
                color="#2563EB"
              />
              <HeroStat
                value={result.changes.reduce((s, c) => s + (c.query_count ?? 0), 0)}
                label="Queries affected"
                tooltip="Sum of usage-telemetry query counts across all impacted objects. Zero if usage data isn't loaded."
                color="#F37440"
              />
            </div>
          </div>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 2 · RISK CLASSIFICATION
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="1. Risk classification"
            subtitle="Each change is scored along two INDEPENDENT dimensions"
            icon={Shield}
            intro={
              <>
                <strong>Severity</strong> (HIGH / MEDIUM / LOW) measures the <em>technical risk</em> of a change —
                how likely it is to cause a production incident.{" "}
                <strong>Breaking</strong> is a separate flag: it means the change <em>breaks backward compatibility</em>{" "}
                (dropping a column referenced by a view, changing a column&apos;s type incompatibly).
                A change can be BREAKING with MEDIUM severity, or HIGH severity but non-breaking.
                That&apos;s why both donuts are shown side-by-side.
              </>
            }
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <DonutChart
                title="By severity (technical risk)"
                data={bySeverity}
                colors={bySeverity.map((d) => SEVERITY_COLORS[d.name] ?? "#7C8185")}
              />
              <DonutChart
                title="Breaking vs non-breaking (compatibility)"
                data={[
                  { name: "Breaking", value: result.changes.filter(c => c.is_breaking).length, detail: "Will break downstream consumers" },
                  { name: "Non-breaking", value: result.changes.filter(c => !c.is_breaking).length, detail: "Backward-compatible" },
                ].filter(d => d.value > 0)}
                colors={["#DC2626", "#16A34A"]}
              />
            </div>
          </GuidedSection>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 3 · BLAST RADIUS
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="2. Impact spread"
            subtitle="How far each change ripples through the dependency graph"
            icon={Zap}
            intro={
              <>
                SCION walks the dependency graph from each changed object outward, counting how many
                downstream tables/views/procs transitively feel the change. <strong>Depth</strong> is
                the number of hops: depth 1 = direct consumer, depth 2 = consumer-of-consumer, and so on.
                The <strong>weighted score</strong> combines breaking × 3 + high-severity × 2 + medium × 1
                + depth bonus — it&apos;s the single number to compare across diffs.
              </>
            }
          >
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <BigStat
                value={result.blast_radius.total_impacted_nodes}
                label="Impacted objects"
                hint="Distinct downstream nodes"
                color="#2563EB"
              />
              <BigStat
                value={result.blast_radius.max_depth}
                label="Max depth"
                hint={`Ripple reaches ${result.blast_radius.max_depth} hop(s) away`}
                color="#00233C"
              />
              <BigStat
                value={result.blast_radius.weighted_score.toFixed(1)}
                label="Weighted impact score"
                hint="Severity × count + depth bonus"
                color="#F37440"
              />
            </div>

            {result.blast_radius.affected_schemas.length > 0 && (
              <div className="mt-4 bg-gray-50 rounded-lg p-3 flex items-center gap-2 flex-wrap">
                <Layers size={14} className="text-td-gray-dark" />
                <span className="text-xs text-td-gray-dark">
                  Touched databases ({result.blast_radius.affected_schemas.length}):
                </span>
                {result.blast_radius.affected_schemas.map((s) => (
                  <span key={s} className="bg-td-navy/10 text-td-navy px-2 py-0.5 rounded text-xs font-medium">
                    {s}
                  </span>
                ))}
              </div>
            )}
          </GuidedSection>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 4 · DISTRIBUTION
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="3. Distribution"
            subtitle="Where the changes land and what kinds they are"
            icon={GitBranch}
            intro={
              <>
                Same change set, two cross-cuts. <strong>By database</strong> tells you which domains
                are carrying the bulk of the churn — useful for spotting a team doing a big release.
                <strong>By type</strong> tells you what&apos;s happening mechanically: a cluster of
                COLUMN_ADDED reads like feature work, a cluster of TABLE_REMOVED reads like decommission.
              </>
            }
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <DonutChart
                title="By database"
                data={bySchema}
                colors={["#00233C", "#16A34A", "#F37440", "#2563EB", "#7C8185"]}
              />
              <DonutChart
                title="By change type"
                data={byChangeType}
                colors={["#DC2626", "#F59E0B", "#0D7377", "#2563EB", "#16A34A", "#7C8185"]}
              />
            </div>
          </GuidedSection>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 5 · PER-CHANGE DRILL-DOWN
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="4. Per-change drill-down"
            subtitle="Every change scored individually"
            icon={ListTree}
            intro={
              <>
                Row-level view. <strong>Direct</strong> = first-hop dependents; <strong>Indirect</strong> =
                everything deeper. <strong>Queries</strong> and <strong>Users</strong> come from the usage
                telemetry layer (empty dash when usage isn&apos;t loaded). The <strong>Score</strong>{" "}
                column is the per-change contribution to the weighted impact score above.
              </>
            }
          >
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-td-navy text-white text-left">
                  <th className="px-4 py-3 font-medium">ID</th>
                  <th className="px-4 py-3 font-medium">Object</th>
                  <th className="px-4 py-3 font-medium">Change</th>
                  <th className="px-4 py-3 font-medium">Severity</th>
                  <th className="px-4 py-3 font-medium">Breaking</th>
                  <th className="px-4 py-3 font-medium">
                    <span className="inline-flex items-center gap-1">Direct <InfoTooltip text="First-level dependents: objects that directly reference this one (1 hop away)." size={11} className="text-white/50" /></span>
                  </th>
                  <th className="px-4 py-3 font-medium">
                    <span className="inline-flex items-center gap-1">Indirect <InfoTooltip text="Deeper impacts: objects that depend on the direct dependents (2+ hops away)." size={11} className="text-white/50" /></span>
                  </th>
                  <th className="px-4 py-3 font-medium" title="Queries currently referencing this object (from Usage data)">Queries</th>
                  <th className="px-4 py-3 font-medium" title="Distinct users running queries on this object">Users</th>
                  <th className="px-4 py-3 font-medium" title="Weighted impact score combining severity, blast radius, and usage">Score</th>
                </tr>
              </thead>
              <tbody>
                {result.changes.map((row) => (
                  <tr key={row.change_id} className="border-t border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-xs">{row.change_id}</td>
                    <td className="px-4 py-3 font-mono text-xs">{row.object_identifier}</td>
                    <td className="px-4 py-3">
                      <span
                        className="bg-td-orange/10 text-td-orange px-2 py-0.5 rounded text-xs font-medium"
                        title={row.change_type}
                      >
                        {changeTypeLabel(row.change_type)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex px-2 py-0.5 rounded-full text-xs font-medium"
                        style={{
                          backgroundColor: `${SEVERITY_COLORS[row.severity] ?? "#7C8185"}20`,
                          color: SEVERITY_COLORS[row.severity] ?? "#7C8185",
                        }}>
                        {row.severity}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      {row.is_breaking && (
                        <span className="bg-red-600 text-white px-2 py-0.5 rounded-full text-xs font-medium">
                          BREAKING
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-center font-bold" style={{ color: IMPACT_COLORS.upstream }}>
                      {row.direct_count}
                    </td>
                    <td className="px-4 py-3 text-center font-bold" style={{ color: IMPACT_COLORS.downstream }}>
                      {row.indirect_count}
                    </td>
                    <td className="px-4 py-3 text-center font-mono text-xs">
                      {row.query_count > 0 ? (
                        <span className="text-td-orange font-semibold" title={`${row.query_count.toLocaleString()} queries touch this object`}>
                          {row.query_count >= 1000 ? `${(row.query_count / 1000).toFixed(1)}K` : row.query_count}
                        </span>
                      ) : <span className="text-gray-400">—</span>}
                    </td>
                    <td className="px-4 py-3 text-center font-mono text-xs">
                      {row.user_count > 0 ? row.user_count : <span className="text-gray-400">—</span>}
                    </td>
                    <td className="px-4 py-3 text-center font-mono text-xs">
                      {row.impact_score > 0 ? row.impact_score.toFixed(2) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </GuidedSection>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 6 · AFFECTED OBJECTS (grouped by database)
              ═══════════════════════════════════════════════════════════ */}
          {result.blast_radius.affected_schemas.length > 0 && (
            <GuidedSection
              title="5. Affected objects, by database"
              subtitle={`${result.blast_radius.affected_tables.length} tables across ${result.blast_radius.affected_schemas.length} databases`}
              icon={Boxes}
              intro={
                <>
                  Flat list of every downstream object SCION detected in the dependency
                  graph. Grouped by database so you can see where the ripple concentrates
                  — useful for deciding which owner teams to notify before a release.
                  A database that appears here with zero tables means the database-level
                  node itself was touched (schema add/remove) but no child objects bubbled up.
                </>
              }
            >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {result.blast_radius.affected_schemas.map((schema) => {
                  const tables = result.blast_radius.affected_tables.filter((t) =>
                    t.startsWith(schema + ".")
                  );
                  return (
                    <div key={schema} className="bg-gray-50 rounded-lg p-3 border border-gray-100">
                      <div className="text-xs font-semibold text-td-navy mb-2 flex items-center gap-2">
                        <Database size={12} />
                        {schema}
                        <span className="text-td-gray-dark font-normal">({tables.length} tables)</span>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {tables.map((t) => (
                          <span key={t} className="bg-white border border-gray-200 text-td-gray-dark px-2 py-0.5 rounded text-[10px] font-mono">
                            {t.split(".").pop()}
                          </span>
                        ))}
                        {tables.length === 0 && (
                          <span className="text-[10px] text-td-gray-dark italic">
                            Database node only — no child objects impacted.
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </GuidedSection>
          )}
        </>
      )}

      {!result && !loading && from == null && (
        <EmptyState message="Select two snapshots on the Changes page, or pick them above." />
      )}
      {!result && !loading && from != null && (
        <EmptyState message="Click 'Analyze Full Diff' to compute impact spread and per-change scoring." />
      )}
    </PageShell>
  );
}

