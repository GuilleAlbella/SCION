"use client";

// Data Lineage page — focused subgraph view around a selected object.
//
// Architecture (changed in v1.17):
//
// Previously this page fetched the entire system graph for the active
// snapshot via ``useGraph(snapshotId)`` and then carved the 5-lane
// subgraph (upstream-2 → upstream-1 → CENTER → downstream-1 →
// downstream-2) in the browser. That was fine on a 150-object demo
// but locked up Chrome on a 337k-node Transcend extract — both
// during the wire transfer and during dagre's O(V³) layout.
//
// Now: the page never loads the full graph. It uses
// ``<ObjectAutocomplete source="graph">`` to let the user search the
// snapshot's catalog server-side, then calls ``GET /graph/focus`` to
// fetch ONLY the BFS subgraph (default 2 hops, capped at 200 nodes).
// The 5-lane lineage layout is still computed in the browser, but
// from a much smaller input. ``capped`` from the server tells us
// when BFS ran out of room, so the UI can suggest widening the
// search.

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
import ObjectAutocomplete from "@/components/shared/ObjectAutocomplete";
import { useSelection } from "@/lib/SelectionContext";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { getFocusedGraph } from "@/lib/api/graph";
import type {
  FocusedGraphResponse,
  GraphNode as GN,
} from "@/lib/api/types";
import { changeTypeLabel } from "@/lib/terminology";
import { GuidedSection } from "@/components/shared/GuidedSection";
import { ArrowUp, ArrowDown, Info, Network, GitBranch, Layers } from "lucide-react";

const NODE_W = 220;
const NODE_H = 60;

// Lineage walks 2 hops in each direction by default — enough to spot
// "is this fed by an external table?" without overloading the layout.
// Caller can extend later if we add a hops control to the UI.
const LINEAGE_HOPS = 2;
// Local nodes cap. The backend hard-caps at 1000; 300 covers any sane
// lineage neighbourhood while leaving headroom for the pathological
// "table feeds 100 reports" case before we'd want to surface a hint.
const LINEAGE_MAX_NODES = 300;

/* ---- Custom nodes for the lineage subgraph ---- */
function UpstreamNode({ data }: { data: { label: string; type: string; metrics?: GN["metrics"] } }) {
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

function CenterNode({ data }: { data: { label: string; type: string; metrics?: GN["metrics"] } }) {
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

function DownstreamNode({ data }: { data: { label: string; type: string; metrics?: GN["metrics"] } }) {
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
  //   1. URL `?snapshot=X` (deep-link from Changes/Impact) — explicit intent
  //   2. `selectedSnap` (manual dropdown pick on this page)
  //   3. `activeDiffPair.snapshotTo` (cross-page SelectionContext fallback)
  const [selectedSnap, setSelectedSnap] = useState<string>("");
  const snapshotId = selectedSnap
    ? Number(selectedSnap)
    : activeDiffPair?.snapshotTo ?? null;

  const [selectedObject, setSelectedObject] = useState<string>("");
  const [focusData, setFocusData] = useState<FocusedGraphResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // When the URL points at a column (3-part identifier like
  // `schema.table.column`), we resolve to the parent table because columns
  // aren't lineage-level nodes in SCION — only databases / tables / views /
  // procs are. `redirectedFromColumn` captures the original column name so
  // we can show an info banner explaining the redirection.
  const [redirectedFromColumn, setRedirectedFromColumn] = useState<string | null>(null);

  // Quick-link entry: ?object=X&snapshot=Y from other pages. URL params
  // ALWAYS win because they represent the user's most recent explicit intent.
  const searchParams = useSearchParams();
  useEffect(() => {
    const objectParam = searchParams.get("object");
    const snapshotParam = searchParams.get("snapshot");
    if (objectParam) {
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

  // Fetch the focused subgraph whenever (snapshot, object) changes. We
  // deliberately do this in a manual effect rather than SWR because the
  // request is keyed on TWO inputs that change together — using SWR
  // would mean composing the cache key out of both anyway, and the
  // payload is small enough that re-fetching on rapid pair changes
  // isn't a perf concern.
  useEffect(() => {
    if (!snapshotId || !selectedObject) {
      setFocusData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getFocusedGraph({
      snapshot_id: snapshotId,
      root: selectedObject,
      hops: LINEAGE_HOPS,
      max_nodes: LINEAGE_MAX_NODES,
      // Lineage is about data flow, so we follow only FEEDS edges.
      // DEPENDS_ON edges (e.g. table→database) are structural and
      // would clutter the picture without adding lineage value.
      edge_types: "FEEDS",
    })
      .then((data) => {
        if (!cancelled) setFocusData(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 404) {
          setFocusData(null);
          setError("Object not found in this snapshot.");
        } else {
          setError(err instanceof Error ? err.message : "Failed to load lineage.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [snapshotId, selectedObject]);

  // ──── Build the 5-lane lineage view from the focused subgraph ────
  // The backend hands us a (capped) BFS neighbourhood; here we tag each
  // node as upstream / center / downstream based on edge directionality
  // relative to the root. The original page did the same thing, just over
  // a much larger candidate set.
  const { nodes, edges, upstreamList, downstreamList, selectedNodeData } = useMemo(() => {
    if (!focusData)
      return {
        nodes: [] as Node[],
        edges: [] as Edge[],
        upstreamList: [] as string[],
        downstreamList: [] as string[],
        selectedNodeData: null as GN | null,
      };

    const nodeMap = new Map(focusData.nodes.map((n) => [n.node_id, n]));
    const selectedNode = focusData.nodes.find(
      (n) => n.object_name === selectedObject || `${n.schema_name}.${n.object_name}` === selectedObject,
    );
    if (!selectedNode)
      return {
        nodes: [] as Node[],
        edges: [] as Edge[],
        upstreamList: [] as string[],
        downstreamList: [] as string[],
        selectedNodeData: null as GN | null,
      };

    // Upstream = nodes that feed INTO selected (FEEDS edge ends at root).
    const upstreamIds = new Set<string>();
    const downstreamIds = new Set<string>();
    for (const e of focusData.edges) {
      if (e.type !== "FEEDS") continue;
      if (e.target === selectedNode.node_id) upstreamIds.add(e.source);
      if (e.source === selectedNode.node_id) downstreamIds.add(e.target);
    }

    // 2nd-level expansion. The focus call already returned a 2-hop
    // neighbourhood, so any node that feeds an upstream node (or that
    // a downstream node feeds) is in the dataset and just needs to
    // be tagged.
    const upstream2 = new Set<string>();
    for (const uid of upstreamIds) {
      for (const e of focusData.edges) {
        if (e.target === uid && e.type === "FEEDS" && e.source !== selectedNode.node_id) {
          upstream2.add(e.source);
        }
      }
    }
    const downstream2 = new Set<string>();
    for (const did of downstreamIds) {
      for (const e of focusData.edges) {
        if (e.source === did && e.type === "FEEDS" && e.target !== selectedNode.node_id) {
          downstream2.add(e.target);
        }
      }
    }

    const rfNodes: Node[] = [];
    const rfEdges: Edge[] = [];
    const added = new Set<string>();

    const pushNode = (id: string, type: "upstream" | "center" | "downstream") => {
      const n = nodeMap.get(id);
      if (!n || added.has(id)) return;
      added.add(id);
      rfNodes.push({
        id,
        type,
        data: {
          label: n.object_name.split(".").pop() ?? n.object_name,
          type: n.object_type,
          metrics: n.metrics,
        },
        position: { x: 0, y: 0 },
      });
    };

    upstream2.forEach((id) => pushNode(id, "upstream"));
    upstreamIds.forEach((id) => pushNode(id, "upstream"));
    pushNode(selectedNode.node_id, "center");
    downstreamIds.forEach((id) => pushNode(id, "downstream"));
    downstream2.forEach((id) => pushNode(id, "downstream"));

    // Only emit edges whose BOTH endpoints landed in the subgraph.
    let ei = 0;
    for (const e of focusData.edges) {
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
  }, [focusData, selectedObject]);

  // If the user ran an Impact analysis earlier, cachedImpactResults tells us
  // whether the selected object was part of that diff — used to show the
  // "Changed in this diff" badge in the detail panel.
  const changeInfo = useMemo(() => {
    if (!selectedObject) return null;
    return cachedImpactResults.find((r) => r.objectIdentifier === selectedObject);
  }, [selectedObject, cachedImpactResults]);

  // Click-handler for the upstream/downstream list items: jumps focus to the
  // clicked object. Wrapped in useCallback so the list rows' inline
  // `onClick={() => setSelectedObject(name)}` doesn't reallocate every render.
  const focusOn = useCallback((name: string) => {
    setSelectedObject(name);
    setRedirectedFromColumn(null);
  }, []);

  return (
    <PageShell title="Data Lineage" subtitle="Where does data come from and where does it go?">
      <div className="bg-blue-50/40 border border-blue-100 rounded-lg px-3 py-2 mb-4 flex items-start gap-2">
        <Info size={12} className="text-blue-500 shrink-0 mt-0.5" />
        <p className="text-[11px] text-td-gray-dark leading-relaxed">
          Lineage answers two operational questions: <strong>if I break this object, what
          downstream breaks with it?</strong> and <strong>if a report is wrong, where might
          the bad data come from?</strong> Pick an object below; SCION traces 2 hops in
          each direction and colours the graph so upstream (red) shows data sources and
          downstream (green) shows data consumers. Search is server-side, so even
          on a 240k-table extract the picker stays instant.
        </p>
      </div>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        <div className="flex items-end gap-4 flex-wrap">
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
          <div className="flex-1 min-w-[280px]">
            <label className="text-xs text-td-gray-dark block mb-1">
              Object of Interest
              <span
                className="ml-1 text-[10px] text-td-gray-dark font-normal"
                title="Type to search the snapshot's catalog. Matches schema.object names."
              >
                — type to search
              </span>
            </label>
            <ObjectAutocomplete
              value={selectedObject}
              onChange={setSelectedObject}
              source="graph"
              snapshotId={snapshotId ?? undefined}
              placeholder={snapshotId ? "Search object by name..." : "Select a snapshot first..."}
              disabled={!snapshotId}
            />
          </div>
        </div>

        {/* Redirected-from-column info banner */}
        {redirectedFromColumn && selectedObject && (
          <div className="mt-3 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 flex items-start gap-2">
            <svg className="text-emerald-600 shrink-0 mt-0.5" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>
            <p className="text-[11px] text-emerald-900 leading-relaxed">
              Original change was on column{" "}
              <strong className="font-mono">{redirectedFromColumn}</strong> — columns aren&apos;t
              lineage-level nodes in SCION, so we&apos;re showing lineage for its parent table{" "}
              <strong className="font-mono">{selectedObject}</strong>.
            </p>
          </div>
        )}

        {focusData?.capped && (
          <div className="mt-3 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-[11px] text-amber-900">
            BFS reached the {LINEAGE_MAX_NODES}-node cap before exhausting {LINEAGE_HOPS} hops.
            The graph below is the largest readable slice; widen the search via Changes
            or pick a more specific object to see the full neighbourhood.
          </div>
        )}
      </div>

      {error && <ErrorAlert message={error} />}
      {loading && <LoadingSpinner />}

      {!snapshotId && !loading && (
        <EmptyState message="Select a snapshot or run a diff first to explore data lineage." />
      )}

      {snapshotId && !selectedObject && !loading && (
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
                      onClick={() => focusOn(name)}>
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
                      onClick={() => focusOn(name)}>
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
