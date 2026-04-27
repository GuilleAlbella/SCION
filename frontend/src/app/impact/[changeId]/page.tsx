"use client";

import { useState, useEffect, use } from "react";
import PageShell from "@/components/layout/PageShell";
import KpiCard from "@/components/shared/KpiCard";
import DonutChart from "@/components/shared/DonutChart";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import { runImpact } from "@/lib/api/impact";
import type { ImpactResponse, ImpactItem } from "@/lib/api/types";
import { IMPACT_COLORS } from "@/lib/constants";
import { ArrowUp, ArrowDown, Info } from "lucide-react";

function groupBy(items: ImpactItem[], key: keyof ImpactItem) {
  const map = new Map<string, number>();
  for (const item of items) {
    const k = String(item[key]) || "Unknown";
    map.set(k, (map.get(k) ?? 0) + 1);
  }
  return Array.from(map, ([name, value]) => ({ name, value }));
}

export default function ImpactDetailPage({
  params,
}: {
  params: Promise<{ changeId: string }>;
}) {
  const { changeId } = use(params);
  const cid = Number(changeId);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImpactResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      try {
        const data = await runImpact(cid);
        if (!cancelled) setResult(data);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    run();
    return () => { cancelled = true; };
  }, [cid]);

  if (loading) return <PageShell title={`Impact — Change #${cid}`}><LoadingSpinner /></PageShell>;
  if (error) return <PageShell title={`Impact — Change #${cid}`}><ErrorAlert message={error} /></PageShell>;
  if (!result) return <PageShell title={`Impact — Change #${cid}`}><ErrorAlert message="No data" /></PageShell>;

  const upstreamByType = groupBy(result.direct_impact, "object_type");
  const downstreamByType = groupBy(result.indirect_impact, "object_type");

  // Detect column-level change: the direct_impact[0] (the changed object
  // itself, inserted at depth=0 by the backend) has object_type COLUMN, or
  // a 3+ segment name. When so, the upstream/downstream numbers come from
  // the PARENT TABLE's propagation — surface that explanation so the user
  // doesn't think we're inflating or misattributing the counts.
  const firstDirect = result.direct_impact[0];
  const isColumnChange = firstDirect && (
    firstDirect.object_type === "COLUMN" ||
    (firstDirect.object_name?.split(".").length ?? 0) >= 3
  );
  const parentTable = isColumnChange
    ? firstDirect.object_name.split(".").slice(0, 2).join(".")
    : null;

  return (
    <PageShell
      title={`Impact Analysis — Change #${cid}`}
      subtitle="Object-level impact detail"
    >
      {/* ──── Column-level "resolved via parent table" banner ────
          v1.10.03: column changes don't have their own graph node, so
          the impact engine resolves to the parent table and traces from
          there. Surfacing this here keeps the numbers honest — users see
          "3 direct" and understand it means "3 consumers of the parent
          table that would feel the column change", not some inflated
          column-specific metric. */}
      {isColumnChange && parentTable && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3 mb-4 flex items-start gap-2">
          <svg className="text-emerald-600 shrink-0 mt-0.5" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>
          <p className="text-xs text-emerald-900 leading-relaxed">
            This change affects column{" "}
            <strong className="font-mono">{firstDirect.object_name}</strong>.
            Columns aren&apos;t graph nodes on their own, so the counts below
            reflect impact traced through the parent table{" "}
            <strong className="font-mono">{parentTable}</strong> — every
            downstream consumer of that table could be affected by this
            column-level change.
          </p>
        </div>
      )}

      {/* Object of Interest */}
      <div className="bg-white rounded-lg shadow-sm border-2 border-td-object p-4 mb-6">
        <div className="flex items-center gap-2 mb-2">
          <Info size={16} className="text-td-object" />
          <h3 className="text-sm font-semibold text-td-object">Object of Interest</h3>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
          <div>
            <span className="text-td-gray-dark">Change ID:</span>{" "}
            <span className="font-mono font-bold">{result.change_id}</span>
          </div>
          <div>
            <span className="text-td-gray-dark">Direct Count:</span>{" "}
            <span className="font-bold">{result.summary.direct_count}</span>
          </div>
          <div>
            <span className="text-td-gray-dark">Indirect Count:</span>{" "}
            <span className="font-bold">{result.summary.indirect_count}</span>
          </div>
          <div>
            <span className="text-td-gray-dark">Total:</span>{" "}
            <span className="font-bold">
              {result.summary.direct_count + result.summary.indirect_count}
            </span>
          </div>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <KpiCard label="# Selected Objects" value={1} color={IMPACT_COLORS.object} />
        <KpiCard label="# Associated Impact" value={result.summary.direct_count + result.summary.indirect_count} />
        <KpiCard label="# Direct" value={result.summary.direct_count} color={IMPACT_COLORS.upstream} />
        <KpiCard label="# Indirect" value={result.summary.indirect_count} color={IMPACT_COLORS.downstream} />
      </div>

      {/* Two columns: upstream / downstream */}
      <div className="grid grid-cols-2 gap-6">
        {/* Upstream */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <ArrowUp size={16} className="text-td-upstream" />
            <h3 className="text-sm font-semibold text-td-upstream">Upstream Impact Summary</h3>
          </div>
          <DonutChart
            title="By Object Type"
            data={upstreamByType}
            colors={["#DC2626", "#F87171", "#991B1B"]}
          />
          <div className="mt-4 bg-white rounded-lg shadow-sm border-2 border-td-upstream p-4">
            <h4 className="text-xs font-semibold text-td-upstream mb-2">
              Upstream Impact Inventory
            </h4>
            <div className="overflow-auto max-h-64">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-td-gray-dark border-b">
                    <th className="pb-1.5 pr-3">Type</th>
                    <th className="pb-1.5 pr-3">Name</th>
                    <th className="pb-1.5 pr-3">Impact</th>
                    <th className="pb-1.5">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {result.direct_impact.map((item, i) => (
                    <tr key={i} className="border-b border-gray-50 align-top">
                      <td className="py-1.5 pr-3 whitespace-nowrap">{item.object_type}</td>
                      <td className="py-1.5 pr-3 font-mono break-all">{item.object_name}</td>
                      <td className="py-1.5 pr-3 whitespace-nowrap">{item.impact_type}</td>
                      <td className="py-1.5 text-td-gray-dark break-words">{item.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Downstream */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            <ArrowDown size={16} className="text-td-downstream" />
            <h3 className="text-sm font-semibold text-td-downstream">Downstream Impact Summary</h3>
          </div>
          <DonutChart
            title="By Object Type"
            data={downstreamByType}
            colors={["#16A34A", "#4ADE80", "#166534"]}
          />
          <div className="mt-4 bg-white rounded-lg shadow-sm border-2 border-td-downstream p-4">
            <h4 className="text-xs font-semibold text-td-downstream mb-2">
              Downstream Impact Inventory
            </h4>
            <div className="overflow-auto max-h-64">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-td-gray-dark border-b">
                    <th className="pb-1.5 pr-3">Type</th>
                    <th className="pb-1.5 pr-3">Name</th>
                    <th className="pb-1.5 pr-3">Impact</th>
                    <th className="pb-1.5">Description</th>
                  </tr>
                </thead>
                <tbody>
                  {result.indirect_impact.map((item, i) => (
                    <tr key={i} className="border-b border-gray-50 align-top">
                      <td className="py-1.5 pr-3 whitespace-nowrap">{item.object_type}</td>
                      <td className="py-1.5 pr-3 font-mono break-all">{item.object_name}</td>
                      <td className="py-1.5 pr-3 whitespace-nowrap">{item.impact_type}</td>
                      <td className="py-1.5 text-td-gray-dark break-words">{item.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </PageShell>
  );
}
