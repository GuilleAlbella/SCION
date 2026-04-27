"use client";

import { useState, useMemo, useCallback, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import PageShell from "@/components/layout/PageShell";
import KpiCard from "@/components/shared/KpiCard";
import EmptyState from "@/components/shared/EmptyState";
import ErrorAlert from "@/components/shared/ErrorAlert";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import { useSelection } from "@/lib/SelectionContext";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { useGraph } from "@/lib/hooks/useGraph";
import { INTERNAL_OBJECT_NAMES } from "@/lib/constants";
import type { GraphNode as GN } from "@/lib/api/types";
import { changeTypeLabel } from "@/lib/terminology";
import { GuidedSection } from "@/components/shared/GuidedSection";
import ObjectPicker from "@/components/shared/ObjectPicker";
import { Search, ArrowUp, ArrowDown, Info, Network, GitBranch, Layers } from "lucide-react";

const NODE_W = 220;
const NODE_H = 60;

/* ---- Custom nodes for the lineage subgraph ---- */
function UpstreamNode({ data }: { data: { label: string; type: string; metrics?: any } }) {
  return (
    <div style={{ background: "#FEF2F2", border: "2px solid #DC2626", borderRadius: 10, padding: "8px 12px", width: NODE_W }}>
      <Handle type="target" position={Position.Top} style={{ background: "#DC2626" }} />
      <Handle type="source" position={Position.Bottom} style={{ background: "#DC2626" }} />
      <div style={{ fontSize: 9, color: "#DC2626", fontWeight: 600, letterSpacing: "0.03em" }}>SOURCE · {data.type}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: "#991B1B" }}>{data.label}</div>
      {data.metrics && <div style={{ fontSize: 9, color: "#B91C1C", marginTop: 2 }}>{data.metrics.in_degree + data.metrics.out_degree} connections</div>}
    </div>
  );
}

function CenterNode({ data }: { data: { label: string; type: string; metrics?: any } }) {
  return (
    <div style={{ background: "#EFF6FF", border: "3px solid #2563EB", borderRadius: 12, padding: "10px 14px", width: NODE_W, boxShadow: "0 4px 12px rgba(37,99,235,0.2)" }}>
      <Handle type="target" position={Position.Top} style={{ background: "#2563EB" }} />
      <Handle type="source" position={Position.Bottom} style={{ background: "#2563EB" }} />
      <div style={{ fontSize: 9, color: "#2563EB", fontWeight: 600 }}>SELECTED · {data.type}</div>
      <div style={{ fontSize: 14, fontWeight: 700, color: "#1E40AF" }}>{data.label}</div>
      {data.metrics && <div style={{ fontSize: 9, color: "#3B82F6", marginTop: 2 }}>{data.metrics.in_degree + data.metrics.out_degree} connections · {((data.metrics.fragility ?? 0) * 100).toFixed(0)}% risk exposure</div>}
    </div>
  );
}

function DownstreamNode({ data }: { data: { label: string; type: string; metrics?: any } }) {
  return (
    <div style={{ background: "#F0FDF4", border: "2px solid #16A34A", borderRadius: 10, padding: "8px 12px", width: NODE_W }}>
      <Handle type="target" position={Position.Top} style={{ background: "#16A34A" }} />
      <Handle type="source" position={Position.Bottom} style={{ background: "#16A34A" }} />
      <div style={{ fontSize: 9, color: "#16A34A", fontWeight: 600, letterSpacing: "0.03em" }}>CONSUMER · {data.type}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: "#166534" }}>{data.label}</div>
      {data.metrics && <div style={{ fontSize: 9, color: "#15803D", marginTop: 2 }}>{data.metrics.in_degree + data.metrics.out_degree} connections</div>}
    </div>
  );
}

const nodeTypes: NodeTypes = {
  upstream: UpstreamNode,
  center: CenterNode,
  downstream: DownstreamNode,
};

function layoutNodes(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 40, ranksep: 80 });
  for (const n of nodes) g.setNode(n.id, { width: NODE_W, height: NODE_H });
  for (const e of edges) g.setEdge(e.source, e.target);
  dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 } };
  });
}

// Next.js 16 requires any component that calls `useSearchParams` to sit under
// a Suspense boundary so the rest of the page can stream. Hence the wrapper —
// the real page logic is in LineagePage below.
export default function LineagePageWrapper() {
  return (
    <Suspense fallback={<PageShell title="Data Lineage"><LoadingSpinner /></PageShell>}>
      <LineagePage />
    </Suspense>
  );
}

function LineagePage() {
  const { activeDiffPair, cachedImpactResults } = useSelection();
  const { data: snapData } = useSnapshots();
  const snapshots = snapData?.snapshots ?? [];

  // Priority for which snapshot to analyse, highest wins:
  //   1. URL `?snapshot=X` (deep-link from Changes/Impact) — user's explicit intent
  //   2. `selectedSnap` (user's manual dropdown pick on this page)
  //   3. `activeDiffPair.snapshotTo` (cross-page SelectionContext fallback)
  // Previously activeDiffPair took precedence, which silently overrode the
  // URL param — so clicking "Lineage" for an object in snap #2 would load
  // snap #10 (whatever diff pair was active) and report the object missing.
  const [selectedSnap, setSelectedSnap] = useState<string>("");
  const snapshotId = selectedSnap
    ? Number(selectedSnap)
    : activeDiffPair?.snapshotTo ?? null;
  const { data: graphData, error: graphError, isLoading } = useGraph(snapshotId);

  const [selectedObject, setSelectedObject] = useState<string | null>(null);

  // When the URL points at a column (3-part identifier like
  // `schema.table.column`), we resolve to the parent table because columns
  // aren't lineage-level nodes in SCION — only databases / tables / views /
  // procs are. `redirectedFromColumn` captures the original column name so
  // we can show an info banner explaining the redirection instead of
  // silently dropping the fragment.
  const [redirectedFromColumn, setRedirectedFromColumn] = useState<string | null>(null);

  // Quick-link entry point: other pages deep-link here with ?object=X&snapshot=Y
  // so the user lands with the graph already focused. URL params ALWAYS win —
  // they represent the user's most recent explicit intent, even if the
  // cross-page SelectionContext has something different cached.
  const searchParams = useSearchParams();
  useEffect(() => {
    const objectParam = searchParams.get("object");
    const snapshotParam = searchParams.get("snapshot");
    if (objectParam) {
      // Heuristic: 3+ dot-separated segments → this is a column (or deeper)
      // and we should focus on the parent table instead. Column-level
      // changes come from Changes page quick-links; they're legitimate
      // but not lineage-addressable on their own.
      const parts = objectParam.split(".");
      if (parts.length >= 3) {
        const parentTable = parts.slice(0, 2).join(".");
        setSelectedObject(parentTable);
        setRedirectedFromColumn(objectParam);
      } else {
        setSelectedObject(objectParam);
        setRedirectedFromColumn(null);
      }
    }
    if (snapshotParam) setSelectedSnap(snapshotParam);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Build object list from graph (excluding internal). Keep both a plain
  // string array (legacy uses below) and an enriched `ObjectEntry[]` for
  // ObjectPicker so it can show per-object type icons.
  const allObjects = useMemo(() => {
    if (!graphData) return [];
    return graphData.nodes
      .filter((n) => !INTERNAL_OBJECT_NAMES.has(n.object_name.split(".").pop() ?? ""))
      .map((n) => n.object_name)
      .sort();
  }, [graphData]);

  const pickerEntries = useMemo(() => {
    if (!graphData) return [];
    return graphData.nodes
      .filter((n) => !INTERNAL_OBJECT_NAMES.has(n.object_name.split(".").pop() ?? ""))
      .map((n) => ({ name: n.object_name, type: n.object_type }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [graphData]);

  // ──── Lineage subgraph builder ────
  // This is the core of the page: from the full system graph we carve out
  // a 5-lane subgraph centered on `selectedObject` — upstream-2, upstream-1,
  // CENTER, downstream-1, downstream-2. Only FEEDS edges count as data flow;
  // DEPENDS_ON edges are structural (e.g. table→database) and intentionally
  // ignored to keep the lineage view about data, not metadata.
  // Depends on `graphData` (network fetch) and `selectedObject` (user pick).
  const { nodes, edges, upstreamList, downstreamList, selectedNodeData } = useMemo(() => {
    if (!graphData || !selectedObject) return { nodes: [] as Node[], edges: [] as Edge[], upstreamList: [] as string[], downstreamList: [] as string[], selectedNodeData: null as GN | null };

    const nodeMap = new Map(graphData.nodes.map((n) => [n.node_id, n]));
    const selectedNode = graphData.nodes.find((n) => n.object_name === selectedObject);
    if (!selectedNode) return { nodes: [] as Node[], edges: [] as Edge[], upstreamList: [] as string[], downstreamList: [] as string[], selectedNodeData: null as GN | null };

    // Find upstream: nodes that have an edge TO the selected node (they feed into it)
    const upstreamIds = new Set<string>();
    for (const e of graphData.edges) {
      if (e.target === selectedNode.node_id && e.type === "FEEDS") {
        upstreamIds.add(e.source);
      }
    }
    // Also check nodes that the selected node DEPENDS_ON (database)
    for (const e of graphData.edges) {
      if (e.source === selectedNode.node_id && e.type === "DEPENDS_ON") {
        // Don't show database as upstream — it's structural, not data flow
      }
    }

    // Find downstream: nodes that have an edge FROM the selected node (it feeds them)
    const downstreamIds = new Set<string>();
    for (const e of graphData.edges) {
      if (e.source === selectedNode.node_id && e.type === "FEEDS") {
        downstreamIds.add(e.target);
      }
    }
    // Also: nodes where selected is the target of a FEEDS (selected feeds them = they depend on selected)
    for (const e of graphData.edges) {
      if (e.target === selectedNode.node_id && e.type === "DEPENDS_ON") {
        // source DEPENDS_ON selected → selected is upstream of source
        // But for lineage we show: who consumes our data
      }
    }

    // 2nd-level expansion: go one more hop away in each direction so users
    // see the broader neighbourhood. We skip edges that point back to the
    // selected node to avoid double-listing it.
    // 2nd level: nodes that feed into downstream nodes or that upstream feeds from
    const upstream2 = new Set<string>();
    for (const uid of upstreamIds) {
      for (const e of graphData.edges) {
        if (e.target === uid && e.type === "FEEDS" && e.source !== selectedNode.node_id) {
          upstream2.add(e.source);
        }
      }
    }
    const downstream2 = new Set<string>();
    for (const did of downstreamIds) {
      for (const e of graphData.edges) {
        if (e.source === did && e.type === "FEEDS" && e.target !== selectedNode.node_id) {
          downstream2.add(e.target);
        }
      }
    }

    // Build React Flow nodes in visual order (upstream-2 → upstream-1 →
    // center → downstream-1 → downstream-2). `added` dedupes since a node
    // could technically appear in more than one level (e.g. cycles).
    const rfNodes: Node[] = [];
    const rfEdges: Edge[] = [];
    const added = new Set<string>();

    // Upstream level 2
    for (const id of upstream2) {
      const n = nodeMap.get(id);
      if (!n || added.has(id)) continue;
      added.add(id);
      rfNodes.push({ id, type: "upstream", data: { label: n.object_name.split(".").pop() ?? n.object_name, type: n.object_type, metrics: n.metrics }, position: { x: 0, y: 0 } });
    }

    // Upstream level 1
    for (const id of upstreamIds) {
      const n = nodeMap.get(id);
      if (!n || added.has(id)) continue;
      added.add(id);
      rfNodes.push({ id, type: "upstream", data: { label: n.object_name.split(".").pop() ?? n.object_name, type: n.object_type, metrics: n.metrics }, position: { x: 0, y: 0 } });
    }

    // Center
    added.add(selectedNode.node_id);
    rfNodes.push({
      id: selectedNode.node_id, type: "center",
      data: { label: selectedNode.object_name.split(".").pop() ?? selectedNode.object_name, type: selectedNode.object_type, metrics: selectedNode.metrics },
      position: { x: 0, y: 0 },
    });

    // Downstream level 1
    for (const id of downstreamIds) {
      const n = nodeMap.get(id);
      if (!n || added.has(id)) continue;
      added.add(id);
      rfNodes.push({ id, type: "downstream", data: { label: n.object_name.split(".").pop() ?? n.object_name, type: n.object_type, metrics: n.metrics }, position: { x: 0, y: 0 } });
    }

    // Downstream level 2
    for (const id of downstream2) {
      const n = nodeMap.get(id);
      if (!n || added.has(id)) continue;
      added.add(id);
      rfNodes.push({ id, type: "downstream", data: { label: n.object_name.split(".").pop() ?? n.object_name, type: n.object_type, metrics: n.metrics }, position: { x: 0, y: 0 } });
    }

    // Only emit edges whose BOTH endpoints landed in the subgraph. This
    // guards against React Flow complaining about dangling edge IDs.
    // Edges (only FEEDS between nodes in our subgraph)
    let ei = 0;
    for (const e of graphData.edges) {
      if (e.type !== "FEEDS") continue;
      if (added.has(e.source) && added.has(e.target)) {
        const isUpstream = upstreamIds.has(e.source) || upstream2.has(e.source);
        const isDownstream = downstreamIds.has(e.target) || downstream2.has(e.target);
        rfEdges.push({
          id: `le-${ei++}`,
          source: e.source,
          target: e.target,
          animated: true,
          style: { stroke: isUpstream ? "#DC2626" : isDownstream ? "#16A34A" : "#2563EB", strokeWidth: 2 },
        });
      }
    }

    const laidOut = layoutNodes(rfNodes, rfEdges);

    return {
      nodes: laidOut,
      edges: rfEdges,
      upstreamList: [...upstreamIds].map((id) => nodeMap.get(id)?.object_name ?? id),
      downstreamList: [...downstreamIds].map((id) => nodeMap.get(id)?.object_name ?? id),
      selectedNodeData: selectedNode,
    };
  }, [graphData, selectedObject]);

  // If the user ran an Impact analysis earlier, cachedImpactResults tells us
  // whether the selected object was part of that diff — used to show the
  // "Changed in this diff" badge in the detail panel.
  const changeInfo = useMemo(() => {
    if (!selectedObject) return null;
    return cachedImpactResults.find((r) => r.objectIdentifier === selectedObject);
  }, [selectedObject, cachedImpactResults]);

  return (
    <PageShell title="Data Lineage" subtitle="Where does data come from and where does it go?">
      {/* Page-level intro — kept compact because this page is visualisation-
          driven and the real "sections" only appear after an object is picked. */}
      <div className="bg-blue-50/40 border border-blue-100 rounded-lg px-3 py-2 mb-4 flex items-start gap-2">
        <Info size={12} className="text-blue-500 shrink-0 mt-0.5" />
        <p className="text-[11px] text-td-gray-dark leading-relaxed">
          Lineage answers two operational questions: <strong>if I break this object, what
          downstream breaks with it?</strong> and <strong>if a report is wrong, where might
          the bad data come from?</strong> Pick an object below; SCION traces 2 hops in
          each direction and colours the graph so upstream (red) shows data sources and
          downstream (green) shows data consumers. The dropdown only lists{" "}
          <strong>databases, tables, views and procedures</strong> — columns aren&apos;t
          lineage-level objects, so for column-level impact use the Changes page instead.
        </p>
      </div>

      {/* Controls — snapshot dropdown is ALWAYS visible so a user who arrived
          via deep-link (?object=X&snapshot=Y) can still switch context without
          losing the selected object. */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        <div className="flex items-end gap-4">
          <div>
            <label className="text-xs text-td-gray-dark block mb-1">Snapshot</label>
            <select
              value={selectedSnap || (snapshotId ? String(snapshotId) : "")}
              onChange={(e) => setSelectedSnap(e.target.value)}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm"
            >
              <option value="">Select</option>
              {snapshots.map((s) => (
                <option key={s.snapshot_id} value={s.snapshot_id}>
                  #{s.snapshot_id} — {s.source_system}
                </option>
              ))}
            </select>
          </div>
          <div className="flex-1">
            <label className="text-xs text-td-gray-dark block mb-1">
              <Search size={12} className="inline mr-1" />
              Object of Interest
              <span
                className="ml-1 text-[10px] text-td-gray-dark font-normal"
                title="Type to search across all objects, or browse by database in the tree."
              >
                — search or drill down
              </span>
            </label>
            <ObjectPicker
              objects={pickerEntries}
              value={selectedObject}
              onChange={setSelectedObject}
              placeholder="Search object or browse by database..."
            />
          </div>
          {snapshotId && (
            <span
              className="text-xs text-td-gray-dark pb-1 whitespace-nowrap"
              title="Counts tables, views, procs and database containers. Columns aren't listed because lineage operates at the object level — use the Changes page for column-level detail."
            >
              Snapshot #{snapshotId} · {allObjects.length} objects
            </span>
          )}
        </div>

        {/* ──── "Redirected from column" info banner ────
            Fires when we came here via a deep-link pointing at a column
            (3-part identifier) and auto-resolved to the parent table.
            Explains the translation so the user doesn't think we silently
            ignored part of the URL. */}
        {redirectedFromColumn && selectedObject && (
          <div className="mt-3 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 flex items-start gap-2">
            <svg className="text-emerald-600 shrink-0 mt-0.5" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>
            <p className="text-[11px] text-emerald-900 leading-relaxed">
              Original change was on column{" "}
              <strong className="font-mono">{redirectedFromColumn}</strong> — columns aren&apos;t
              lineage-level nodes in SCION, so we&apos;re showing lineage for its parent table{" "}
              <strong className="font-mono">{selectedObject}</strong>. For column-level impact
              detail, see the Changes page.
            </p>
          </div>
        )}

        {/* ──── "Object not found in this snapshot" hint ────
            Fires when we have a graph loaded AND the user has a pre-selected
            object (e.g. from a deep-link) that doesn't exist in this
            particular snapshot. Covers the common case where someone
            clicks Lineage on a schema/table that was added in a later
            snapshot or removed in an earlier one. */}
        {graphData && selectedObject && !allObjects.includes(selectedObject) && (
          <div className="mt-3 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 flex items-start gap-2">
            <svg className="text-amber-500 shrink-0 mt-0.5" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            <p className="text-[11px] text-amber-900 leading-relaxed">
              <strong className="font-mono">{selectedObject}</strong> isn&apos;t present in snapshot
              #{snapshotId}. It may have been added in a later snapshot or removed in an earlier
              one. Try switching the Snapshot dropdown above — for example, the snapshot where
              the change was detected.
            </p>
          </div>
        )}
      </div>

      {graphError && <ErrorAlert message="Failed to load graph" />}
      {isLoading && <LoadingSpinner />}

      {!snapshotId && !isLoading && (
        <EmptyState message="Select a snapshot or run a diff first to explore data lineage." />
      )}

      {snapshotId && !selectedObject && !isLoading && (
        <EmptyState message="Pick an object above to see where its data comes from and where it goes." />
      )}

      {selectedObject && selectedNodeData && (
        <>
          {/* ═══════════════════════════════════════════════════════════
              SECTION 1 · Lineage graph
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="1. Lineage graph"
            subtitle="Visual trace of upstream producers and downstream consumers"
            icon={GitBranch}
            intro={
              <>
                The selected object sits in the middle (blue). <strong>Red nodes on the left</strong>{" "}
                feed data into it — upstream producers, 1 or 2 hops away. <strong>Green nodes on the right</strong>{" "}
                consume data from it — downstream reports, pipelines, and views.
                KPIs at the top count each direction. Click any node in the graph to jump
                to its own lineage.
              </>
            }
          >
          {/* KPIs */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <KpiCard label="Feeds data from" value={upstreamList.length} color="#DC2626" />
            <KpiCard label="Sends data to" value={downstreamList.length} color="#16A34A" />
            <KpiCard label="Related objects" value={nodes.length} color="#2563EB" />
            <KpiCard label="Data flows" value={edges.length} color="#00233C" />
          </div>

          {/* Lineage graph */}
          {nodes.length > 1 ? (
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden mb-6" style={{ height: 450 }}>
              <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                fitView
                minZoom={0.3}
                maxZoom={2}
                attributionPosition="bottom-left"
              >
                <Background gap={16} size={1} />
                <Controls />
              </ReactFlow>
            </div>
          ) : (
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-8 text-center text-sm text-td-gray-dark mb-6">
              <Network size={32} className="mx-auto mb-2 opacity-30" />
              No direct data relationships found for this object. Try selecting a table that references other tables.
            </div>
          )}

          {/* Legend */}
          <div className="flex items-center gap-6 text-xs text-td-gray-dark">
            <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded border-2 border-red-600 bg-red-50" /> Provides data</div>
            <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded border-2 border-blue-600 bg-blue-50" /> Selected object</div>
            <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded border-2 border-green-600 bg-green-50" /> Receives data</div>
            <div className="flex items-center gap-1.5"><span className="w-6 border-t-2 border-dashed border-blue-500" /> Data flow</div>
          </div>
          </GuidedSection>

          {/* ═══════════════════════════════════════════════════════════
              SECTION 2 · Detail panels
              ═══════════════════════════════════════════════════════════ */}
          <GuidedSection
            title="2. Producers, details, and consumers"
            subtitle="The lineage as three side-by-side lists"
            icon={Layers}
            intro={
              <>
                Same information as the graph above, re-shaped as lists for quick scanning.
                Click any row on the left or right to make that object the focus.
                The middle card shows catalog metadata (object type, database, graph
                in/out-degree) plus a <strong>&ldquo;Changed in this diff&rdquo; badge</strong> if
                the selected object was part of your last Impact Analysis run.
              </>
            }
          >
          <div className="grid grid-cols-3 gap-4">
            {/* Upstream */}
            <div className="bg-white rounded-lg shadow-sm border-2 border-td-upstream p-4">
              <div className="flex items-center gap-2 mb-3">
                <ArrowUp size={16} className="text-td-upstream" />
                <h3 className="text-sm font-semibold text-td-upstream">Where data comes from ({upstreamList.length})</h3>
              </div>
              {upstreamList.length === 0 ? (
                <p className="text-xs text-td-gray-dark">This is a source table — data originates here.</p>
              ) : (
                <ul className="space-y-1">
                  {upstreamList.map((name) => (
                    <li key={name} className="text-xs font-mono bg-red-50 rounded px-2 py-1 text-red-800 cursor-pointer hover:bg-red-100"
                      onClick={() => setSelectedObject(name)}>
                      {name}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Object info */}
            <div className="bg-white rounded-lg shadow-sm border-2 border-td-object p-4">
              <div className="flex items-center gap-2 mb-3">
                <Info size={16} className="text-td-object" />
                <h3 className="text-sm font-semibold text-td-object">Object Details</h3>
              </div>
              <div className="space-y-2 text-xs">
                <div><span className="text-td-gray-dark">Name:</span> <span className="font-mono font-medium">{selectedNodeData.object_name.split(".").pop()}</span></div>
                <div><span className="text-td-gray-dark">Database:</span> <span className="font-mono">{selectedNodeData.schema_name}</span></div>
                <div><span className="text-td-gray-dark">Type:</span> <span className="font-medium">{selectedNodeData.object_type}</span></div>
                {selectedNodeData.metrics && (
                  <>
                    <div className="grid grid-cols-2 gap-2 pt-2 border-t border-gray-100">
                      <div className="bg-gray-50 rounded p-1.5 text-center">
                        <div className="text-sm font-bold">{selectedNodeData.metrics.in_degree}</div>
                        <div className="text-[9px] text-td-gray-dark">Incoming</div>
                      </div>
                      <div className="bg-gray-50 rounded p-1.5 text-center">
                        <div className="text-sm font-bold">{selectedNodeData.metrics.out_degree}</div>
                        <div className="text-[9px] text-td-gray-dark">Outgoing</div>
                      </div>
                    </div>
                  </>
                )}
                {changeInfo && (
                  <div className="bg-orange-50 rounded p-2 border border-orange-200 mt-2">
                    <div className="text-xs font-semibold text-td-orange">Changed in this diff</div>
                    <div className="text-[10px] text-td-gray-dark" title={changeInfo.changeType}>{changeTypeLabel(changeInfo.changeType)} · {changeInfo.severity}</div>
                  </div>
                )}
              </div>
            </div>

            {/* Downstream */}
            <div className="bg-white rounded-lg shadow-sm border-2 border-td-downstream p-4">
              <div className="flex items-center gap-2 mb-3">
                <ArrowDown size={16} className="text-td-downstream" />
                <h3 className="text-sm font-semibold text-td-downstream">Where data goes ({downstreamList.length})</h3>
              </div>
              {downstreamList.length === 0 ? (
                <p className="text-xs text-td-gray-dark">This is an endpoint — no other objects consume this data directly.</p>
              ) : (
                <ul className="space-y-1">
                  {downstreamList.map((name) => (
                    <li key={name} className="text-xs font-mono bg-green-50 rounded px-2 py-1 text-green-800 cursor-pointer hover:bg-green-100"
                      onClick={() => setSelectedObject(name)}>
                      {name}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
          </GuidedSection>
        </>
      )}
    </PageShell>
  );
}
