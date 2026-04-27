"use client";

import { useMemo, useState, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import PageShell from "@/components/layout/PageShell";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { useSelection } from "@/lib/SelectionContext";
import { useSnapshots } from "@/lib/hooks/useSnapshots";
import { useGraph } from "@/lib/hooks/useGraph";
import { INTERNAL_OBJECT_NAMES } from "@/lib/constants";
import type { GraphNode as GN } from "@/lib/api/types";
import ObjectPicker from "@/components/shared/ObjectPicker";
import { Focus, X as CloseIcon } from "lucide-react";

const NODE_WIDTH = 240;
const NODE_HEIGHT = 70;

const TYPE_STYLES: Record<string, { bg: string; accent: string; text: string; icon: string; label: string }> = {
  SCHEMA:           { bg: "#EFF6FF", accent: "#3B82F6", text: "#1E40AF", icon: "DB", label: "Database" },
  DATABASE:         { bg: "#EFF6FF", accent: "#3B82F6", text: "#1E40AF", icon: "DB", label: "Database" },
  TABLE:            { bg: "#F0FDF4", accent: "#22C55E", text: "#166534", icon: "T",  label: "Table" },
  VIEW:             { bg: "#FFF7ED", accent: "#F97316", text: "#9A3412", icon: "V",  label: "View" },
  STORED_PROCEDURE: { bg: "#F5F3FF", accent: "#8B5CF6", text: "#5B21B6", icon: "SP", label: "Stored Proc" },
  MACRO:            { bg: "#FDF4FF", accent: "#D946EF", text: "#86198F", icon: "M",  label: "Macro" },
  FUNCTION:         { bg: "#ECFEFF", accent: "#06B6D4", text: "#155E75", icon: "F",  label: "Function" },
  UDF:              { bg: "#ECFEFF", accent: "#06B6D4", text: "#155E75", icon: "U",  label: "UDF" },
  TRIGGER:          { bg: "#FEF2F2", accent: "#EF4444", text: "#991B1B", icon: "TR", label: "Trigger" },
  INDEX:            { bg: "#FEFCE8", accent: "#EAB308", text: "#854D0E", icon: "I",  label: "Index" },
  // UNKNOWN = parser v1 didn't send `datasetType`. Rendered in amber to
  // match the "Structural snapshot incomplete" warning surfaced at import.
  UNKNOWN:          { bg: "#FFFBEB", accent: "#F59E0B", text: "#92400E", icon: "?",  label: "Unclassified" },
};
const DEFAULT_STYLE = { bg: "#F9FAFB", accent: "#9CA3AF", text: "#374151", icon: "?", label: "Other" };
const UNKNOWN_TOOLTIP = "Waiting for parser datasetType field. Object ingested but not classified as table/view/procedure.";

function fragilityColor(f: number): string {
  if (f >= 0.10) return "#DC2626";
  if (f >= 0.05) return "#F59E0B";
  return "#22C55E";
}

/* ---- Custom Node Component ---- */
function GraphNodeComponent({ data }: { data: { raw: GN } }) {
  const n = data.raw;
  const s = TYPE_STYLES[n.object_type] ?? DEFAULT_STYLE;
  const frag = n.metrics?.fragility ?? 0;
  const displayName = n.object_name.includes(".")
    ? n.object_name.split(".").pop()!
    : n.object_name;
  const schemaLabel = n.schema_name || "";
  const isUnclassified = n.object_type === "UNKNOWN";

  return (
    <div
      title={isUnclassified ? UNKNOWN_TOOLTIP : undefined}
      style={{
        background: s.bg,
        border: `2px ${isUnclassified ? "dashed" : "solid"} ${s.accent}`,
        borderRadius: 10,
        padding: "8px 12px",
        width: NODE_WIDTH,
        minHeight: NODE_HEIGHT,
        position: "relative",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: s.accent }} />
      <Handle type="source" position={Position.Bottom} style={{ background: s.accent }} />

      {/* Type badge */}
      <div style={{
        position: "absolute", top: -10, left: 12,
        background: s.accent, color: "white",
        fontSize: 9, fontWeight: 700, padding: "1px 6px",
        borderRadius: 4, letterSpacing: "0.05em",
      }}>
        {s.label.toUpperCase()}
      </div>

      {/* Name */}
      <div style={{ color: s.text, fontSize: 13, fontWeight: 600, marginTop: 4 }}>
        {displayName}
      </div>

      {/* Database */}
      {schemaLabel && n.object_type !== "SCHEMA" && n.object_type !== "DATABASE" && (
        <div style={{ color: s.text, fontSize: 10, opacity: 0.6 }}>
          {schemaLabel}
        </div>
      )}

      {/* Metrics row */}
      {n.metrics && (
        <div style={{ display: "flex", gap: 8, marginTop: 4, fontSize: 9, color: "#6B7280" }}>
          <span>in:{n.metrics.in_degree}</span>
          <span>out:{n.metrics.out_degree}</span>
          <span style={{ color: fragilityColor(frag), fontWeight: 600 }}>
            frag:{(frag * 100).toFixed(0)}%
          </span>
          {n.metrics.is_hub && (
            <span style={{ color: "#F59E0B", fontWeight: 700 }}>★HUB</span>
          )}
        </div>
      )}
    </div>
  );
}

const nodeTypes: NodeTypes = { custom: GraphNodeComponent };

/* ---- Layout helper ----
   We use dagre for a deterministic top-down layered layout. React Flow's
   built-in auto-layout is position-based; dagre gives us proper hierarchical
   ranks so "upstream above, downstream below" reads naturally. */
function layoutGraph(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 60, ranksep: 80 });

  for (const node of nodes) g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  for (const edge of edges) g.setEdge(edge.source, edge.target);

  dagre.layout(g);

  return nodes.map((node) => {
    const pos = g.node(node.id);
    return { ...node, position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 } };
  });
}

/* ---- Page ---- */
export default function GraphPage() {
  const { activeSnapshotId, setActiveSnapshotId } = useSelection();
  const { data: snapData } = useSnapshots();
  const { data: graphData, error, isLoading } = useGraph(activeSnapshotId);
  const [selectedNode, setSelectedNode] = useState<GN | null>(null);
  const [showSchemas, setShowSchemas] = useState(true);
  const [edgeFilter, setEdgeFilter] = useState<"ALL" | "DEPENDS_ON" | "FEEDS">("ALL");

  // ──── Focus mode (Meeting #7 / Kindy + Rahul) ────
  // At Lloyds-scale (500M relationships) rendering the whole graph is
  // pointless. Focus mode lets the user pick an anchor object and N hops;
  // we BFS out from that anchor in both directions and render only the
  // reachable subgraph. Falls through to "show everything" when no anchor
  // is set, so existing behaviour is preserved.
  const [focusObject, setFocusObject] = useState<string | null>(null);
  const [hops, setHops] = useState<number>(2);

  // Heavy memoized pipeline: filter internal nodes → optionally hide schemas →
  // filter edges by endpoint membership and by type → build React Flow nodes
  // and edges → run dagre → compute stats. Runs only when inputs change.
  const { nodes, edges, stats, focusMissing } = useMemo(() => {
    if (!graphData) return { nodes: [], edges: [], stats: { schemas: 0, tables: 0, views: 0, unclassified: 0, feedsEdges: 0, dependsEdges: 0 }, focusMissing: false };

    let filteredNodes = graphData.nodes.filter(
      (n) => !INTERNAL_OBJECT_NAMES.has(n.object_name.split(".").pop() ?? "")
    );

    if (!showSchemas) {
      filteredNodes = filteredNodes.filter((n) => n.object_type !== "SCHEMA");
    }

    // ──── Focus BFS ────
    // When an anchor is set, carve out the subgraph within `hops` edges
    // (undirected) from that anchor. Both FEEDS and DEPENDS_ON edges count
    // as traversal steps regardless of the edgeFilter below — the edge
    // filter is cosmetic (what we *render*), not a reachability filter.
    let focusMissingLocal = false;
    if (focusObject) {
      const anchor = filteredNodes.find((n) => n.object_name === focusObject);
      if (!anchor) {
        focusMissingLocal = true;
        filteredNodes = [];
      } else {
        // Adjacency list from the (pre-filter) graph so hops can cross
        // hidden containers — otherwise turning off "Database nodes"
        // would silently break the BFS.
        const adj = new Map<string, string[]>();
        for (const e of graphData.edges) {
          if (!adj.has(e.source)) adj.set(e.source, []);
          if (!adj.has(e.target)) adj.set(e.target, []);
          adj.get(e.source)!.push(e.target);
          adj.get(e.target)!.push(e.source);
        }
        const reachable = new Set<string>([anchor.node_id]);
        let frontier: string[] = [anchor.node_id];
        for (let depth = 0; depth < hops; depth++) {
          const next: string[] = [];
          for (const id of frontier) {
            for (const nb of adj.get(id) ?? []) {
              if (!reachable.has(nb)) {
                reachable.add(nb);
                next.push(nb);
              }
            }
          }
          if (next.length === 0) break;
          frontier = next;
        }
        filteredNodes = filteredNodes.filter((n) => reachable.has(n.node_id));
      }
    }

    const nodeIds = new Set(filteredNodes.map((n) => n.node_id));

    const rfNodes: Node[] = filteredNodes.map((n) => ({
      id: n.node_id,
      type: "custom",
      data: { raw: n },
      position: { x: 0, y: 0 },
    }));

    // Drop edges whose endpoints were filtered out — React Flow would throw
    // on dangling edges otherwise.
    let filteredEdges = graphData.edges.filter(
      (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
    );
    if (edgeFilter !== "ALL") {
      filteredEdges = filteredEdges.filter((e) => e.type === edgeFilter);
    }

    const rfEdges: Edge[] = filteredEdges.map((e, i) => {
      const isFeed = e.type === "FEEDS";
      return {
        id: `e-${i}`,
        source: e.source,
        target: e.target,
        label: e.type,
        style: {
          stroke: isFeed ? "#3B82F6" : "#CBD5E1",
          strokeWidth: isFeed ? 2.5 : 1.5,
          strokeDasharray: isFeed ? "6,3" : undefined,
        },
        labelStyle: { fontSize: 8, fill: isFeed ? "#3B82F6" : "#94A3B8" },
        labelBgStyle: { fill: "white", fillOpacity: 0.8 },
        animated: isFeed,
      };
    });

    const laidOut = layoutGraph(rfNodes, rfEdges);

    // `unclassified` surfaces the count of UNKNOWN-type nodes so a parser-v1
    // import doesn't look deceptively empty in the header ("0 tables" is
    // technically true but hides real data).
    const stats = {
      schemas: filteredNodes.filter((n) => n.object_type === "SCHEMA" || n.object_type === "DATABASE").length,
      tables: filteredNodes.filter((n) => n.object_type === "TABLE").length,
      views: filteredNodes.filter((n) => n.object_type === "VIEW").length,
      unclassified: filteredNodes.filter((n) => n.object_type === "UNKNOWN").length,
      feedsEdges: filteredEdges.filter((e) => e.type === "FEEDS").length,
      dependsEdges: filteredEdges.filter((e) => e.type === "DEPENDS_ON").length,
    };

    return { nodes: laidOut, edges: rfEdges, stats, focusMissing: focusMissingLocal };
  }, [graphData, showSchemas, edgeFilter, focusObject, hops]);

  const snapshots = snapData?.snapshots ?? [];

  // Picker entries — same filtering as the rendered graph but keep the
  // full catalog so users can still anchor on objects hidden by Schemas
  // toggle etc. (the BFS re-introduces anything reachable).
  const pickerEntries = useMemo(() => {
    if (!graphData) return [];
    return graphData.nodes
      .filter((n) => !INTERNAL_OBJECT_NAMES.has(n.object_name.split(".").pop() ?? ""))
      .map((n) => ({ name: n.object_name, type: n.object_type }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [graphData]);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    setSelectedNode((node.data as { raw: GN }).raw);
  }, []);

  return (
    <PageShell title="System Graph" subtitle="Technical dependency & lineage visualization">
      {/* Page-level intro — compact because the page is visualisation-driven.
          Legend at the bottom of the page carries the formal explanation of
          shapes / colours / fragility; this intro sells the value of the view. */}
      <div className="bg-blue-50/40 border border-blue-100 rounded-lg px-3 py-2 mb-4 flex items-start gap-2">
        <svg className="text-blue-500 shrink-0 mt-0.5" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
        <p className="text-[11px] text-td-gray-dark leading-relaxed">
          A bird&apos;s-eye view of the entire warehouse as a graph:{" "}
          <strong>nodes = database objects</strong> (tables, views, procs, …),{" "}
          <strong>edges = dependencies</strong> (what feeds what).
          Use the filter bar to narrow by edge type (DEPENDS_ON vs FEEDS) or hide
          database-level container nodes. For large warehouses, set{" "}
          <strong>Focus on object</strong> to carve out a neighbourhood of N hops
          around any anchor — the whole-graph view isn&apos;t readable past a few
          hundred nodes. Click any node to see its metrics on the right —
          in-degree, out-degree, fragility, hub status.
        </p>
      </div>

      {/* ──── Controls bar ──── Snapshot picker + edge-type filter + schema toggle + live counts */}
      <div className="flex items-center gap-4 mb-4 flex-wrap">
        <div>
          <label className="text-xs text-td-gray-dark block mb-1">Snapshot</label>
          <select
            value={activeSnapshotId ?? ""}
            onChange={(e) => {
              setActiveSnapshotId(e.target.value ? Number(e.target.value) : null);
              setSelectedNode(null);
            }}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm"
          >
            <option value="">Select snapshot</option>
            {snapshots.map((s) => (
              <option key={s.snapshot_id} value={s.snapshot_id}>
                #{s.snapshot_id} — {s.source_system}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-xs text-td-gray-dark block mb-1">Edges</label>
          <div className="flex gap-1">
            {(["ALL", "DEPENDS_ON", "FEEDS"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setEdgeFilter(f)}
                className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                  edgeFilter === f
                    ? "bg-td-navy text-white"
                    : "bg-gray-100 text-td-gray-dark hover:bg-gray-200"
                }`}
              >
                {f === "ALL" ? "All" : f}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="text-xs text-td-gray-dark block mb-1">Show</label>
          <label className="flex items-center gap-1.5 text-xs cursor-pointer">
            <input
              type="checkbox"
              checked={showSchemas}
              onChange={(e) => setShowSchemas(e.target.checked)}
              className="rounded"
            />
            Database nodes
          </label>
        </div>

        {graphData && (
          <div className="flex-1 min-w-[240px] max-w-[420px]">
            <label className="text-xs text-td-gray-dark block mb-1 flex items-center gap-1">
              <Focus size={12} className="inline" />
              Focus on object
              <span className="text-[10px] text-gray-400 font-normal" title="Narrow the graph to a neighbourhood around one object. Useful when the full graph has thousands of nodes.">
                (optional, scales to large graphs)
              </span>
            </label>
            <ObjectPicker
              objects={pickerEntries}
              value={focusObject}
              onChange={setFocusObject}
              placeholder="Show entire graph — or pick an anchor..."
            />
          </div>
        )}

        {focusObject && (
          <div>
            <label className="text-xs text-td-gray-dark block mb-1">
              Hops: <strong>{hops}</strong>
            </label>
            <input
              type="range"
              min={1}
              max={5}
              value={hops}
              onChange={(e) => setHops(Number(e.target.value))}
              className="w-28"
              title="How many edges away from the anchor to include. 1 = direct neighbours only; 5 = wide neighbourhood."
            />
          </div>
        )}

        {focusObject && (
          <button
            onClick={() => setFocusObject(null)}
            className="text-xs text-blue-600 hover:underline flex items-center gap-1 self-end pb-1.5"
            title="Clear focus and show the entire graph"
          >
            <CloseIcon size={10} /> Clear focus
          </button>
        )}

        {graphData && (
          <div className="ml-auto flex gap-3 text-xs text-td-gray-dark items-center">
            <span>{stats.schemas} databases</span>
            <span>{stats.tables} tables</span>
            <span>{stats.views} views</span>
            {stats.unclassified > 0 && (
              <span
                className="px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 font-medium"
                title={UNKNOWN_TOOLTIP}
              >
                {stats.unclassified} unclassified
              </span>
            )}
            <span className="text-blue-500">{stats.feedsEdges} FEEDS</span>
            <span className="text-gray-400">{stats.dependsEdges} DEPENDS_ON</span>
          </div>
        )}
      </div>

      {focusObject && !focusMissing && nodes.length > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 mb-3 flex items-start gap-2 text-[11px] text-blue-900">
          <Focus size={12} className="shrink-0 mt-0.5 text-blue-500" />
          <div>
            Focus mode: showing <strong>{nodes.length}</strong> objects within <strong>{hops}</strong> hop{hops === 1 ? "" : "s"} of{" "}
            <span className="font-mono">{focusObject}</span>. Pull the slider right to widen the neighbourhood, or click &ldquo;Clear focus&rdquo; to see the whole graph.
          </div>
        </div>
      )}
      {focusMissing && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-3 text-[11px] text-amber-900">
          Anchor <span className="font-mono">{focusObject}</span> isn&apos;t present in this snapshot. Try a different snapshot or clear the focus.
        </div>
      )}

      {!activeSnapshotId && <EmptyState message="Select a snapshot to visualize its dependency graph." />}
      {error && <ErrorAlert message="Failed to load graph data" />}
      {isLoading && <LoadingSpinner />}

      {graphData && nodes.length > 0 && (
        <div className="flex gap-4">
          <div
            className="flex-1 bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden"
            style={{ height: 620 }}
          >
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodeClick={onNodeClick}
              fitView
              minZoom={0.2}
              maxZoom={2}
              attributionPosition="bottom-left"
            >
              <Background gap={16} size={1} />
              <Controls />
              <MiniMap
                style={{ height: 100, width: 150 }}
                maskColor="rgba(0,35,60,0.1)"
              />
            </ReactFlow>
          </div>

          {/* Detail sidebar */}
          {selectedNode && (
            <div className="w-72 bg-white rounded-lg shadow-sm border border-gray-200 p-4 self-start">
              <h3 className="text-sm font-semibold text-td-navy mb-3">Node Details</h3>
              <div className="space-y-2 text-xs">
                <div className="flex items-center gap-2">
                  <span
                    className="px-1.5 py-0.5 rounded text-white text-[10px] font-bold"
                    style={{ background: (TYPE_STYLES[selectedNode.object_type] ?? DEFAULT_STYLE).accent }}
                  >
                    {(TYPE_STYLES[selectedNode.object_type] ?? DEFAULT_STYLE).label.toUpperCase()}
                  </span>
                </div>
                <div>
                  <span className="text-td-gray-dark">Full name:</span>
                  <div className="font-mono font-medium mt-0.5">{selectedNode.object_name}</div>
                </div>
                <div>
                  <span className="text-td-gray-dark">Database:</span>{" "}
                  <span className="font-mono">{selectedNode.schema_name}</span>
                </div>
                {selectedNode.metrics && (
                  <>
                    <hr className="border-gray-100" />
                    <div className="font-semibold text-td-navy">Graph Metrics</div>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="bg-gray-50 rounded p-2 text-center">
                        <div className="text-lg font-bold text-td-navy">{selectedNode.metrics.in_degree}</div>
                        <div className="text-[10px] text-td-gray-dark">Incoming</div>
                      </div>
                      <div className="bg-gray-50 rounded p-2 text-center">
                        <div className="text-lg font-bold text-td-navy">{selectedNode.metrics.out_degree}</div>
                        <div className="text-[10px] text-td-gray-dark">Outgoing</div>
                      </div>
                    </div>
                    <div>
                      <span className="text-td-gray-dark">Fragility:</span>{" "}
                      <span
                        className="font-bold"
                        style={{ color: fragilityColor(selectedNode.metrics.fragility) }}
                      >
                        {(selectedNode.metrics.fragility * 100).toFixed(1)}%
                      </span>
                    </div>
                    {selectedNode.metrics.is_hub && (
                      <div className="bg-amber-50 text-amber-800 px-2 py-1 rounded text-xs font-medium text-center">
                        ★ Hub Node — High Connectivity
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {graphData && nodes.length === 0 && (
        <EmptyState message="No objects found for this snapshot." />
      )}

      {/* ──── Legend ──── Three independent visual encodings in one legend:
          box color = object type, edge style = relationship kind,
          inline "frag:N%" text color = fragility bucket. Deliberately separate
          so users can read each dimension independently. */}
      {graphData && nodes.length > 0 && (
        <div className="mt-4 bg-white rounded-lg shadow-sm border border-gray-200 p-3 space-y-2">
          <div className="flex items-start gap-4 flex-wrap text-xs">
            {/* Object type (box color) — only show types present in the graph */}
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-td-navy">Object type:</span>
              {(() => {
                const present = new Set(graphData.nodes.map(n => n.object_type));
                return Object.entries(TYPE_STYLES)
                  .filter(([type]) => present.has(type))
                  .filter(([type], idx, arr) => {
                    // Merge DATABASE and SCHEMA visually (same style)
                    if (type === "SCHEMA") return !arr.find(([t]) => t === "DATABASE" && present.has("DATABASE"));
                    return true;
                  })
                  .map(([type, s]) => (
                    <div key={type} className="flex items-center gap-1.5" title={`${s.label} node`}>
                      <span className="w-4 h-4 rounded" style={{ background: s.bg, border: `2px solid ${s.accent}` }} />
                      <span className="text-td-gray-dark">{s.label}</span>
                    </div>
                  ));
              })()}
            </div>

            {/* Edges */}
            <div className="flex items-center gap-3 border-l border-gray-200 pl-4">
              <span className="font-semibold text-td-navy">Relationship:</span>
              <div className="flex items-center gap-1.5" title="DEPENDS_ON: this object references another">
                <span className="w-6 border-t-2" style={{ borderColor: "#CBD5E1" }} />
                <span className="text-td-gray-dark">depends on</span>
              </div>
              <div className="flex items-center gap-1.5" title="FEEDS: this object sends data to another">
                <span className="w-6 border-t-2 border-dashed" style={{ borderColor: "#3B82F6" }} />
                <span className="text-td-gray-dark">feeds data to</span>
              </div>
            </div>

            {/* Fragility (inline text) */}
            <div className="flex items-center gap-3 border-l border-gray-200 pl-4">
              <span className="font-semibold text-td-navy" title="Fragility = in_degree / (in_degree + out_degree). Shown as text inside each node (e.g. 'frag:25%').">
                Fragility (text):
              </span>
              <span className="flex items-center gap-1 text-td-gray-dark"><span className="w-2.5 h-2.5 rounded-full bg-green-500" />&lt;5% low</span>
              <span className="flex items-center gap-1 text-td-gray-dark"><span className="w-2.5 h-2.5 rounded-full bg-amber-500" />5-10% medium</span>
              <span className="flex items-center gap-1 text-td-gray-dark"><span className="w-2.5 h-2.5 rounded-full bg-red-500" />≥10% high</span>
            </div>
          </div>
          <p className="text-[10px] text-td-gray-dark italic">
            Note: box color = object type. Fragility appears as coloured text inside each node (not on the border). Hub nodes (★) have many connections.
          </p>
        </div>
      )}
    </PageShell>
  );
}
