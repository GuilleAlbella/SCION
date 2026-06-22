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
// fetch ONLY the BFS subgraph (default 2 hops, user-adjustable 1-5 via
// the depth stepper, capped at LINEAGE_MAX_NODES nodes).
// The 5-lane lineage layout is still computed in the browser, but
// from a much smaller input. ``capped`` from the server tells us
// when BFS ran out of room, so the UI can suggest widening the
// search.

import { useState, useMemo, useCallback, useEffect, useRef, Suspense } from "react";
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
import { getColumnLineage, getFocusedGraph } from "@/lib/api/graph";
import type {
  ColumnLineageResponse,
  FocusedGraphResponse,
  GraphNode as GN,
  IndirectEdge,
} from "@/lib/api/types";
import { changeTypeLabel } from "@/lib/terminology";
import { GuidedSection } from "@/components/shared/GuidedSection";
import { ArrowUp, ArrowDown, Info, Network, GitBranch, Layers, ChevronDown, ChevronUp } from "lucide-react";

const NODE_W = 220;
const NODE_H = 60;

// Lineage walks N hops in each direction. Default 2 — enough to spot
// "is this fed by an external table?" without overloading the layout —
// but the depth stepper (added for the Reunion 11 "step-by-step" ask)
// lets the user drop to 1 (immediate neighbours only, the cleanest
// starting point on a huge real-world graph) or climb to 5. The
// backend /graph/focus caps hops at 5, so we mirror that here.
const LINEAGE_DEFAULT_HOPS = 2;
const LINEAGE_MIN_HOPS = 1;
const LINEAGE_MAX_HOPS = 5;
// Local nodes cap. The backend hard-caps at 1000; 300 covers any sane
// lineage neighbourhood while leaving headroom for the pathological
// "table feeds 100 reports" case before we'd want to surface a hint.
const LINEAGE_MAX_NODES = 300;

// Heights for expanded nodes (when column lineage is active)
const COL_ROW_H = 19;  // px per column row
const COL_TOP_PAD = 8; // padding above the column strip
const MAX_COLS_SHOWN = 7;

type NodeData = { label: string; type: string; metrics?: GN["metrics"]; columns?: string[] };

/* ── Transformation-type icon badge (Feature 2) ─────────────────────── */
// Maps the 10 parser-emitted transformation_type values to a single
// Unicode glyph + descriptive tooltip. The glyphs were chosen so that
// the intent is legible at 9 px without a font-icon library:
//   → direct value pass-through   ⊿ funnel (filter / join predicate)
//   Σ aggregation                 ƒ computed expression
//   ⊞ window function             ⊟ group-by key
//   ≠ type coercion               ? unknown
const TRANSFORM_GLYPHS: Record<string, { g: string; tip: string }> = {
  "Direct Copy":  { g: "→",  tip: "Direct Copy"    },
  "Filter":       { g: "⊿",  tip: "Filter"         },
  "Aggregate":    { g: "Σ",  tip: "Aggregate"       },
  "Type Cast":    { g: "≠",  tip: "Type Cast"       },
  "Join":         { g: "⊿",  tip: "Join predicate"  },
  "Expression":   { g: "ƒ",  tip: "Expression"      },
  "Window":       { g: "⊞",  tip: "Window function" },
  "Group By":     { g: "⊟",  tip: "Group By key"    },
};

function TransformBadge({
  type,
  className = "",
}: {
  type: string | null;
  className?: string;
}) {
  if (!type) return null;
  const info = TRANSFORM_GLYPHS[type] ?? { g: "·", tip: type };
  return (
    <span
      title={info.tip}
      aria-label={info.tip}
      className={`shrink-0 font-bold cursor-default select-none ${className}`}
    >
      {info.g}
    </span>
  );
}

/* ── Indirect impacts section inside a column card ── */
function IndirectSection({
  indirect,
  expanded,
  onToggle,
}: {
  indirect: IndirectEdge[];
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="bg-amber-50 border-t border-amber-100">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-1.5 px-3 py-1.5 text-[9px] font-bold text-amber-700 uppercase tracking-widest hover:bg-amber-100 transition-colors"
      >
        <span className="flex-1 text-left">
          ⊿ Indirect impacts ({indirect.length})
        </span>
        {expanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
      </button>
      {expanded && (
        <div className="px-3 pb-2 space-y-1.5">
          <p className="text-[8px] text-amber-600 leading-snug mb-1">
            Used in filter / join — affects which rows flow, not which value is copied.
          </p>
          {indirect.map((e, i) => (
            <div key={i} className="flex items-start gap-1.5">
              <TransformBadge
                type={e.transformation_type}
                className="text-[10px] bg-amber-200 text-amber-800 rounded px-1 py-0.5 whitespace-nowrap mt-0.5"
              />
              {e.expression ? (
                <span
                  className="font-mono text-[9px] text-amber-900 break-all leading-tight"
                  title={e.expression}
                >
                  {e.expression.length > 70
                    ? e.expression.slice(0, 70) + "…"
                    : e.expression}
                </span>
              ) : (
                <span className="text-[9px] text-amber-500 italic">no expression</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Column strip rendered inside expanded nodes ── */
function ColumnStrip({ columns, accent }: { columns: string[]; accent: string }) {
  const shown = columns.slice(0, MAX_COLS_SHOWN);
  const extra = columns.length - shown.length;
  return (
    <div style={{ borderTop: `1px solid ${accent}30`, marginTop: 7, paddingTop: 5 }}>
      {shown.map((col) => (
        <div key={col} style={{
          display: "flex", alignItems: "center", gap: 5,
          fontSize: 9, fontFamily: "monospace", color: "#5B21B6",
          background: "rgba(109,40,217,0.08)", borderRadius: 3,
          padding: "2px 6px", marginBottom: 2,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#8B5CF6", flexShrink: 0, display: "inline-block" }} />
          {col}
        </div>
      ))}
      {extra > 0 && <div style={{ fontSize: 8, color: "#8B5CF6", paddingLeft: 8, marginTop: 1 }}>+{extra} more</div>}
    </div>
  );
}

/* ---- Custom nodes for the lineage subgraph ---- */
function UpstreamNode({ data }: { data: NodeData }) {
  return (
    <div style={{ background: "#FEF2F2", border: "2px solid #DC2626", borderRadius: 10, padding: "8px 12px", width: NODE_W, cursor: "pointer" }}>
      <Handle type="target" position={Position.Top} style={{ background: "#DC2626" }} />
      <Handle type="source" position={Position.Bottom} style={{ background: "#DC2626" }} />
      <div style={{ fontSize: 9, color: "#DC2626", fontWeight: 600, letterSpacing: "0.03em" }}>SOURCE · {data.type}</div>
      <div title={data.label} style={{ fontSize: 13, fontWeight: 600, color: "#991B1B", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{data.label}</div>
      {data.metrics && <div style={{ fontSize: 9, color: "#B91C1C", marginTop: 2 }}>{data.metrics.in_degree + data.metrics.out_degree} connections</div>}
      {data.columns && data.columns.length > 0 && <ColumnStrip columns={data.columns} accent="#DC2626" />}
    </div>
  );
}

function CenterNode({ data }: { data: NodeData }) {
  return (
    <div style={{ background: "#EFF6FF", border: "3px solid #2563EB", borderRadius: 12, padding: "10px 14px", width: NODE_W, boxShadow: "0 4px 12px rgba(37,99,235,0.2)", cursor: "default" }}>
      <Handle type="target" position={Position.Top} style={{ background: "#2563EB" }} />
      <Handle type="source" position={Position.Bottom} style={{ background: "#2563EB" }} />
      <div style={{ fontSize: 9, color: "#2563EB", fontWeight: 600 }}>SELECTED · {data.type}</div>
      <div title={data.label} style={{ fontSize: 14, fontWeight: 700, color: "#1E40AF", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{data.label}</div>
      {data.metrics && <div style={{ fontSize: 9, color: "#3B82F6", marginTop: 2 }}>{data.metrics.in_degree + data.metrics.out_degree} connections · {((data.metrics.fragility ?? 0) * 100).toFixed(0)}% risk exposure</div>}
      {data.columns && data.columns.length > 0 && <ColumnStrip columns={data.columns} accent="#2563EB" />}
    </div>
  );
}

function DownstreamNode({ data }: { data: NodeData }) {
  return (
    <div style={{ background: "#F0FDF4", border: "2px solid #16A34A", borderRadius: 10, padding: "8px 12px", width: NODE_W, cursor: "pointer" }}>
      <Handle type="target" position={Position.Top} style={{ background: "#16A34A" }} />
      <Handle type="source" position={Position.Bottom} style={{ background: "#16A34A" }} />
      <div style={{ fontSize: 9, color: "#16A34A", fontWeight: 600, letterSpacing: "0.03em" }}>CONSUMER · {data.type}</div>
      <div title={data.label} style={{ fontSize: 13, fontWeight: 600, color: "#166534", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{data.label}</div>
      {data.metrics && <div style={{ fontSize: 9, color: "#15803D", marginTop: 2 }}>{data.metrics.in_degree + data.metrics.out_degree} connections</div>}
      {data.columns && data.columns.length > 0 && <ColumnStrip columns={data.columns} accent="#16A34A" />}
    </div>
  );
}

const nodeTypes: NodeTypes = {
  upstream: UpstreamNode,
  center: CenterNode,
  downstream: DownstreamNode,
};

function layoutNodes(nodes: Node[], edges: Edge[], nodeHeightMap?: Map<string, number>): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 40, ranksep: 80 });
  for (const n of nodes) {
    const h = nodeHeightMap?.get(n.id) ?? NODE_H;
    g.setNode(n.id, { width: NODE_W, height: h });
  }
  for (const e of edges) g.setEdge(e.source, e.target);
  dagre.layout(g);
  return nodes.map((n) => {
    const h = nodeHeightMap?.get(n.id) ?? NODE_H;
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - NODE_W / 2, y: pos.y - h / 2 } };
  });
}

// Union two directed focus responses (upstream-only + downstream-only)
// into one. See the fetch effect for why lineage walks each direction
// separately instead of relying on the backend's undirected `both`.
// Nodes dedupe by node_id; edges dedupe by (source, target, type);
// `capped` is true if either walk hit its node cap.
function mergeFocusedGraphs(
  up: FocusedGraphResponse,
  down: FocusedGraphResponse,
): FocusedGraphResponse {
  const nodes = new Map<string, GN>();
  for (const n of up.nodes) nodes.set(n.node_id, n);
  for (const n of down.nodes) nodes.set(n.node_id, n);

  const edges = new Map<string, FocusedGraphResponse["edges"][number]>();
  for (const e of [...up.edges, ...down.edges]) {
    edges.set(`${e.source}|${e.target}|${e.type}`, e);
  }

  return {
    ...up,
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    capped: up.capped || down.capped,
  };
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

  // How many hops the lineage walks in each direction. Driven by the
  // depth stepper so the user can reveal the graph "step by step"
  // (start at 1, expand) or cap it on a huge neighbourhood.
  const [hops, setHops] = useState<number>(LINEAGE_DEFAULT_HOPS);

  // Traversal direction. On a hub object (hundreds of direct
  // relationships) `both` blows past the node cap at depth 1; letting
  // the user view producers (`up`) or consumers (`down`) on their own
  // halves the load and usually fits the full picture. Maps straight
  // to the /graph/focus `direction` param.
  const [direction, setDirection] = useState<"both" | "up" | "down">("both");

  // Column-level lineage for the currently selected node (bottom panel).
  const [columnLineage, setColumnLineage] = useState<ColumnLineageResponse | null>(null);
  const [colLineageLoading, setColLineageLoading] = useState(false);

  // Which column card has its "Indirect impacts" section expanded.
  // null = all collapsed; string = column_name of the expanded card.
  const [expandedIndirect, setExpandedIndirect] = useState<string | null>(null);

  // Column lineage graph overlay — toggle + map over ALL visible nodes.
  const [showColumnLineage, setShowColumnLineage] = useState(false);
  const [columnLineageMap, setColumnLineageMap] = useState<Map<string, ColumnLineageResponse>>(new Map());
  const [colMapLoading, setColMapLoading] = useState(false);

  // Feature 3: floating popup for the last clicked column-to-column edge.
  // x/y are coordinates relative to the graph container so the popup
  // appears at the click point, inside the canvas.
  const [clickedEdge, setClickedEdge] = useState<{
    labels: string[];
    steps: string[];
    x: number;
    y: number;
  } | null>(null);
  const graphContainerRef = useRef<HTMLDivElement>(null);

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
    const base = {
      snapshot_id: snapshotId,
      root: selectedObject,
      hops,
      max_nodes: LINEAGE_MAX_NODES,
      // Lineage is about data flow, so we follow only FEEDS edges.
      // DEPENDS_ON edges (e.g. table→database) are structural and
      // would clutter the picture without adding lineage value.
      edge_types: "FEEDS",
    };
    // For "both" we issue TWO *directed* fetches (up + down) and union
    // them, rather than one `direction=both` call. The backend's `both`
    // is an UNDIRECTED BFS: from an upstream hub it also walks that hub's
    // OWN downstream consumers — siblings of the root that aren't on its
    // lineage path at all. On a real graph those siblings flood the
    // node cap (e.g. a 1-in/1-out table whose single producer is a view
    // feeding 567 objects), so the user gets a "too big" warning while
    // only a couple of relevant nodes render. Two directed walks keep
    // the result to the root's true ancestors + descendants.
    //
    // We use allSettled (not all) so a failure in one direction doesn't
    // suppress the other. A source node has no upstream (up returns 404)
    // but still has a valid downstream; an endpoint has no downstream.
    // With Promise.all, either failure would kill the whole render and
    // show a spurious "Network Error" or "Object not found" even though
    // the object exists — exactly the Bug 3 symptom Rahul reported.
    const request: Promise<FocusedGraphResponse> =
      direction === "both"
        ? Promise.allSettled([
            getFocusedGraph({ ...base, direction: "up" }),
            getFocusedGraph({ ...base, direction: "down" }),
          ]).then(([upResult, downResult]) => {
            const up = upResult.status === "fulfilled" ? upResult.value : null;
            const down = downResult.status === "fulfilled" ? downResult.value : null;
            if (up && down) return mergeFocusedGraphs(up, down);
            if (up) return up;
            if (down) return down;
            // Both failed — surface the first rejection so the caller's
            // catch block can show a meaningful error.
            const firstErr =
              upResult.status === "rejected" ? upResult.reason : downResult.status === "rejected" ? downResult.reason : new Error("Failed to load lineage.");
            return Promise.reject(firstErr);
          })
        : getFocusedGraph({ ...base, direction });
    request
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
  }, [snapshotId, selectedObject, hops, direction]);

  // Fetch column-level lineage whenever the selected object changes (bottom panel).
  useEffect(() => {
    if (!snapshotId || !selectedObject) {
      setColumnLineage(null);
      return;
    }
    let cancelled = false;
    setColLineageLoading(true);
    getColumnLineage(snapshotId, selectedObject)
      .then((data) => { if (!cancelled) setColumnLineage(data); })
      .catch(() => { if (!cancelled) setColumnLineage(null); })
      .finally(() => { if (!cancelled) setColLineageLoading(false); });
    return () => { cancelled = true; };
  }, [snapshotId, selectedObject]);

  // Fetch column lineage for EVERY visible node when the graph overlay toggle is ON.
  useEffect(() => {
    if (!showColumnLineage || !focusData || !snapshotId) {
      setColumnLineageMap(new Map());
      return;
    }
    setColMapLoading(true);
    const objects = focusData.nodes
      .filter((n) => !["SCHEMA", "DATABASE"].includes(n.object_type))
      .map((n) => (n.object_name.includes(".") ? n.object_name : `${n.schema_name}.${n.object_name}`));
    Promise.allSettled(
      objects.map((obj) =>
        getColumnLineage(snapshotId, obj).then((r) => [obj.toUpperCase(), r] as const),
      ),
    ).then((results) => {
      const m = new Map<string, ColumnLineageResponse>();
      for (const r of results)
        if (r.status === "fulfilled" && r.value[1].total_edges > 0)
          m.set(r.value[0], r.value[1]);
      setColumnLineageMap(m);
      setColMapLoading(false);
    });
  }, [showColumnLineage, focusData, snapshotId]);

  // ──── Build the 5-lane lineage view from the focused subgraph ────
  // The backend hands us a (capped) BFS neighbourhood; here we tag each
  // node as upstream / center / downstream based on edge directionality
  // relative to the root. The original page did the same thing, just over
  // a much larger candidate set.
  const { nodes, edges, upstreamList, downstreamList, selectedNodeData, isSelfReferencing } = useMemo(() => {
    if (!focusData)
      return {
        nodes: [] as Node[],
        edges: [] as Edge[],
        upstreamList: [] as string[],
        downstreamList: [] as string[],
        selectedNodeData: null as GN | null,
        isSelfReferencing: false,
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
        isSelfReferencing: false,
      };

    // Generalised N-hop BFS over FEEDS edges. We walk upstream (follow
    // edges backwards: a node that feeds the frontier) and downstream
    // (follow edges forwards: a node fed by the frontier) to whatever
    // depth the focus call returned, tagging each reachable node with
    // its direction and 1-based hop distance from the root. This
    // replaces the old hard-coded 2-level tagging so the depth stepper
    // can render 1..5 levels in each direction.
    // Self-loop edges (source === target) arise when a table reads from and
    // writes to itself in the same SQL (e.g. INSERT INTO T SELECT … FROM T).
    // We exclude them from the dagre graph to prevent layout crashes, but
    // track them separately so the side panels can flag the pattern.
    const selfLoopNodeIds = new Set<string>(
      focusData.edges
        .filter((e) => e.type === "FEEDS" && e.source === e.target)
        .map((e) => e.source),
    );
    const feedsEdges = focusData.edges.filter(
      (e) => e.type === "FEEDS" && e.source !== e.target,
    );
    const rootId = selectedNode.node_id;

    // First assignment wins; we run the upstream BFS before the
    // downstream one, so a node sitting on a cycle is labelled by its
    // upstream path (deterministic across renders). The root stays
    // "center".
    const direction = new Map<string, "upstream" | "center" | "downstream">();
    const depthOf = new Map<string, number>();
    direction.set(rootId, "center");
    depthOf.set(rootId, 0);

    const walk = (dir: "upstream" | "downstream") => {
      let frontier = new Set<string>([rootId]);
      let level = 0;
      while (frontier.size > 0) {
        level += 1;
        const next = new Set<string>();
        for (const e of feedsEdges) {
          // upstream: producers (edge target in frontier → add source)
          // downstream: consumers (edge source in frontier → add target)
          const inFrontier = dir === "upstream" ? frontier.has(e.target) : frontier.has(e.source);
          if (!inFrontier) continue;
          const candidate = dir === "upstream" ? e.source : e.target;
          if (direction.has(candidate)) continue;
          direction.set(candidate, dir);
          depthOf.set(candidate, level);
          next.add(candidate);
        }
        frontier = next;
      }
    };
    walk("upstream");
    walk("downstream");

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

    // Push every tagged node. dagre assigns layout ranks from the edge
    // structure, so we don't need to pre-sort by depth.
    for (const [id, dir] of direction) pushNode(id, dir);

    // Only emit FEEDS edges whose BOTH endpoints landed in the subgraph.
    // Colour by direction: any edge touching an upstream node is red,
    // any touching a downstream node is green, otherwise blue.
    let ei = 0;
    for (const e of feedsEdges) {
      if (!added.has(e.source) || !added.has(e.target)) continue;
      const srcDir = direction.get(e.source);
      const tgtDir = direction.get(e.target);
      const stroke =
        srcDir === "upstream" || tgtDir === "upstream"
          ? "#DC2626"
          : srcDir === "downstream" || tgtDir === "downstream"
            ? "#16A34A"
            : "#2563EB";
      rfEdges.push({
        id: `le-${ei++}`,
        source: e.source,
        target: e.target,
        animated: true,
        style: { stroke, strokeWidth: 2 },
      });
    }

    // ── Column lineage overlay ──────────────────────────────────────
    // Build a lookup: uppercase "SCHEMA.TABLE" → ReactFlow node id.
    const nodeIdByKey = new Map<string, string>();
    for (const n of focusData.nodes) {
      const k = (n.object_name.includes(".")
        ? n.object_name
        : `${n.schema_name}.${n.object_name}`
      ).toUpperCase();
      nodeIdByKey.set(k, n.node_id);
    }

    // Which columns are mapped for each node (for the column strip).
    const colsByNode = new Map<string, string[]>();
    if (showColumnLineage) {
      for (const [objKey, lineage] of columnLineageMap) {
        const nid = nodeIdByKey.get(objKey);
        if (nid) colsByNode.set(nid, lineage.columns.map((c) => c.column_name));
      }
    }

    // Inject column strips + compute per-node heights.
    const nodeHeightMap = new Map<string, number>();
    const rfNodesFinal = rfNodes.map((n) => {
      const cols = colsByNode.get(n.id);
      if (!cols || cols.length === 0) return n;
      const shown = Math.min(cols.length, MAX_COLS_SHOWN);
      const extra = cols.length > MAX_COLS_SHOWN ? 1 : 0;
      nodeHeightMap.set(n.id, NODE_H + COL_TOP_PAD + (shown + extra) * COL_ROW_H);
      return { ...n, data: { ...n.data, columns: cols } };
    });

    // Dim table-level edges when column overlay is active.
    const tableEdgesFinal = rfEdges.map((e) =>
      showColumnLineage && columnLineageMap.size > 0
        ? { ...e, style: { ...e.style, opacity: 0.3 }, animated: false }
        : e,
    );

    // Build column-to-column edges, grouped by node pair.
    // pairSteps accumulates unique step_natural_key values per pair so
    // Feature 3 (edge click → step detail) can surface the originating SQL.
    const colEdges: Edge[] = [];
    if (showColumnLineage) {
      const pairLabels = new Map<string, string[]>();
      const pairSteps = new Map<string, Set<string>>();
      for (const [objKey, lineage] of columnLineageMap) {
        const srcId = nodeIdByKey.get(objKey);
        if (!srcId || !added.has(srcId)) continue;
        for (const col of lineage.columns) {
          for (const edge of col.downstream) {
            const tgtId = nodeIdByKey.get(edge.table_key.toUpperCase());
            if (!tgtId || !added.has(tgtId) || tgtId === srcId) continue;
            const pk = `${srcId}||${tgtId}`;
            if (!pairLabels.has(pk)) pairLabels.set(pk, []);
            pairLabels.get(pk)!.push(
              `${col.column_name} → ${edge.column_name}${edge.transformation_type ? `  ·  ${edge.transformation_type}` : ""}`,
            );
            if (edge.step_natural_key) {
              if (!pairSteps.has(pk)) pairSteps.set(pk, new Set());
              pairSteps.get(pk)!.add(edge.step_natural_key);
            }
          }
        }
      }
      let ci = 0;
      for (const [pk, labels] of pairLabels) {
        const [srcId, tgtId] = pk.split("||");
        const steps = [...(pairSteps.get(pk) ?? [])];
        colEdges.push({
          id: `col-${ci++}`,
          source: srcId,
          target: tgtId,
          label: `${labels.length} col${labels.length !== 1 ? "s" : ""}`,
          data: { labels, steps },
          type: "smoothstep",
          style: { stroke: "#7C3AED", strokeWidth: 1.5, strokeDasharray: "5 3" },
          labelStyle: { fontSize: 9, fill: "#6D28D9", fontWeight: 700 },
          labelBgStyle: { fill: "#F5F3FF", fillOpacity: 0.95, rx: 8, ry: 8 },
          labelBgPadding: [4, 6] as [number, number],
          animated: false,
        });
      }
    }

    const allEdges = [...tableEdgesFinal, ...colEdges];
    const laidOut = layoutNodes(rfNodesFinal, allEdges, nodeHeightMap);

    // The side lists keep their "immediate producers / consumers"
    // meaning: only depth-1 neighbours, no matter how deep the graph
    // now goes.
    const directNeighbours = (dir: "upstream" | "downstream") =>
      [...direction.entries()]
        .filter(([id, d]) => d === dir && depthOf.get(id) === 1)
        .map(([id]) => nodeMap.get(id)?.object_name ?? id);

    return {
      nodes: laidOut,
      edges: allEdges,
      upstreamList: directNeighbours("upstream"),
      downstreamList: directNeighbours("downstream"),
      selectedNodeData: selectedNode,
      isSelfReferencing: selfLoopNodeIds.has(String(rootId)),
    };
  }, [focusData, selectedObject, showColumnLineage, columnLineageMap]);

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

  // Click-handler for nodes IN THE GRAPH diagram: re-focus the lineage on
  // the clicked object, mirroring the upstream/downstream list rows (and
  // the Graph page's own onNodeClick). Until this was wired, clicking a
  // node in the diagram did nothing — even though the section intro
  // promised "Click any node in the graph to jump to its own lineage".
  // That gap is the click-to-expand bug surfaced in the Reunion 11 demo.
  const onNodeClick = useCallback(
    (_: unknown, node: Node) => {
      // Ignore clicks on the already-centered node — re-focusing on it
      // would just re-fetch the same neighbourhood.
      if (selectedNodeData && node.id === selectedNodeData.node_id) return;
      const clicked = focusData?.nodes.find((n) => n.node_id === node.id);
      if (!clicked) return;
      // `object_name` is stored already schema-qualified in graph_node
      // (e.g. "ACC_TED_VW.td_ps_ff_transactions"), so use it as-is when it
      // contains a dot. Only prepend the schema for the rare unqualified
      // node — prepending unconditionally produced "schema.schema.object"
      // and an ugly (if accidentally-resolvable) identifier.
      const identifier = clicked.object_name.includes(".")
        ? clicked.object_name
        : clicked.schema_name
          ? `${clicked.schema_name}.${clicked.object_name}`
          : clicked.object_name;
      focusOn(identifier);
    },
    [focusData, selectedNodeData, focusOn],
  );

  // Feature 3: clicking a column-to-column edge (dashed purple) opens a
  // floating popup inside the graph at the click coordinates.
  // Table-level edges (solid colour, no `data`) are intentionally ignored.
  const onEdgeClick = useCallback((event: React.MouseEvent, edge: Edge) => {
    if (!edge.data || !Array.isArray((edge.data as { labels?: unknown }).labels)) return;
    const rect = graphContainerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const POPUP_W = 288; // w-72
    const POPUP_H = 200; // rough estimate
    const rawX = event.clientX - rect.left + 12;
    const rawY = event.clientY - rect.top + 12;
    setClickedEdge({
      ...(edge.data as { labels: string[]; steps: string[] }),
      x: Math.max(4, Math.min(rawX, rect.width - POPUP_W - 4)),
      y: Math.max(4, Math.min(rawY, rect.height - POPUP_H - 4)),
    });
  }, []);

  return (
    <PageShell title="Data Lineage" subtitle="Where does data come from and where does it go?">
      <div className="bg-blue-50/40 border border-blue-100 rounded-lg px-3 py-2 mb-4 flex items-start gap-2">
        <Info size={12} className="text-blue-500 shrink-0 mt-0.5" />
        <p className="text-[11px] text-td-gray-dark leading-relaxed">
          Lineage answers two operational questions: <strong>if I break this object, what
          downstream breaks with it?</strong> and <strong>if a report is wrong, where might
          the bad data come from?</strong> Pick an object below; SCION traces lineage
          outward in each direction and colours the graph so upstream (red) shows data
          sources and downstream (green) shows data consumers. Use the <strong>Depth</strong>{" "}
          control to reveal the graph step by step — start at 1 level and expand up to 5.
          Search is server-side, so even on a 240k-table extract the picker stays instant.
        </p>
      </div>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        <div className="flex items-end gap-4 flex-wrap">
          <div>
            <label className="text-xs text-td-gray-dark block mb-1">Snapshot</label>
            <select
              value={selectedSnap || (snapshotId ? String(snapshotId) : "")}
              onChange={(e) => {
                  setSelectedSnap(e.target.value);
                  // Clear any stale "Object not found" error from the
                  // previous snapshot — the object may exist in the new
                  // one.  Also reset the graph data so the canvas doesn't
                  // show a stale neighbourhood from the wrong snapshot.
                  setError(null);
                  setFocusData(null);
                  setSelectedObject("");
                }}
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
          {/* Depth stepper — reveal lineage "step by step" (start at 1,
              expand) or cap it on a huge neighbourhood. Re-fetches the
              focus subgraph at the chosen hop count. */}
          <div>
            <label className="text-xs text-td-gray-dark block mb-1">
              Depth
              <span
                className="ml-1 text-[10px] text-td-gray-dark font-normal"
                title="How many hops of lineage to walk in each direction. Start at 1 to see only immediate producers/consumers, then step up to reveal more levels."
              >
                — levels each way
              </span>
            </label>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setHops((h) => Math.max(LINEAGE_MIN_HOPS, h - 1))}
                disabled={!selectedObject || hops <= LINEAGE_MIN_HOPS}
                className="w-7 h-7 rounded border border-gray-300 text-sm font-semibold text-td-gray-dark disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50"
                aria-label="Show one fewer level"
              >
                −
              </button>
              <span className="w-8 text-center text-sm font-semibold tabular-nums">{hops}</span>
              <button
                type="button"
                onClick={() => setHops((h) => Math.min(LINEAGE_MAX_HOPS, h + 1))}
                disabled={!selectedObject || hops >= LINEAGE_MAX_HOPS}
                className="w-7 h-7 rounded border border-gray-300 text-sm font-semibold text-td-gray-dark disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-50"
                aria-label="Show one more level"
              >
                +
              </button>
            </div>
          </div>
          {/* Direction filter — on a hub object, viewing producers or
              consumers on their own halves the node count and usually
              fits the full picture instead of hitting the cap. */}
          <div>
            <label className="text-xs text-td-gray-dark block mb-1">
              Direction
              <span
                className="ml-1 text-[10px] text-td-gray-dark font-normal"
                title="Walk both directions, or focus on just the upstream producers / downstream consumers. Filtering one side helps when an object has too many relationships to show at once."
              >
                — what to walk
              </span>
            </label>
            <div className="inline-flex rounded border border-gray-300 overflow-hidden">
              {([
                ["both", "Both"],
                ["up", "Upstream"],
                ["down", "Downstream"],
              ] as const).map(([value, dirLabel]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setDirection(value)}
                  disabled={!selectedObject}
                  className={`px-2.5 py-1.5 text-xs font-medium border-l border-gray-300 first:border-l-0 disabled:opacity-40 disabled:cursor-not-allowed ${
                    direction === value
                      ? "bg-td-object text-white"
                      : "bg-white text-td-gray-dark hover:bg-gray-50"
                  }`}
                >
                  {dirLabel}
                </button>
              ))}
            </div>
          </div>

          {/* Column lineage toggle */}
          <div className="ml-auto">
            <label className="text-xs text-td-gray-dark block mb-1">
              Column detail
              <span className="ml-1 text-[10px] text-td-gray-dark font-normal">— show in graph</span>
            </label>
            <button
              type="button"
              disabled={!selectedObject || !focusData}
              onClick={() => setShowColumnLineage((v) => !v)}
              className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold border transition-all disabled:opacity-40 disabled:cursor-not-allowed ${
                showColumnLineage
                  ? "bg-purple-600 border-purple-600 text-white shadow-md shadow-purple-200"
                  : "bg-white border-gray-300 text-td-gray-dark hover:border-purple-400 hover:text-purple-600"
              }`}
            >
              <GitBranch size={12} />
              {colMapLoading ? "Loading…" : showColumnLineage ? "Column view ON" : "Column view"}
            </button>
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
            {hops === LINEAGE_MIN_HOPS ? (
              // Capped at depth 1 → genuine hub: the object's OWN direct
              // degree is what overflows, so it's worth citing.
              <>
                Showing the first {LINEAGE_MAX_NODES} objects — this object has more
                direct relationships than fit in one view
                {selectedNodeData?.metrics &&
                  ` (${selectedNodeData.metrics.in_degree} incoming + ${selectedNodeData.metrics.out_degree} outgoing in the full graph)`}
                .{" "}
                {direction === "both" ? (
                  <>
                    Tip: switch <strong>Direction</strong> to <strong>Upstream</strong>{" "}
                    or <strong>Downstream</strong> to see each side on its own.
                  </>
                ) : (
                  <>Even this single direction exceeds the cap, so only part is shown.</>
                )}
              </>
            ) : (
              // Capped at depth ≥2 → it's the BREADTH of the multi-hop
              // neighbourhood, not the node itself. Citing the node's own
              // degree here is misleading (a 1-in/1-out node still reaches
              // hundreds at 5 hops); steer toward depth / direction instead.
              <>
                Showing the first {LINEAGE_MAX_NODES} objects — the {hops}-hop
                neighbourhood reaches more than that. Tip: lower the{" "}
                <strong>Depth</strong>
                {direction === "both" && (
                  <> or switch <strong>Direction</strong> to one side</>
                )}{" "}
                to see the full picture.
              </>
            )}
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

      {/* Object exists in snapshot but the parser captured no lineage edges for it */}
      {selectedObject && !loading && !error && focusData && !selectedNodeData && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 flex items-start gap-3">
          <Info size={14} className="text-amber-500 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-900">No lineage recorded for this object</p>
            <p className="text-xs text-amber-700 mt-0.5">
              <strong>{selectedObject}</strong> exists in snapshot #{snapshotId} but the parser did not capture any upstream or downstream relationships for it. This is expected for objects that appear only as standalone targets in INSERT statements or whose SQL was not part of the parsed extract.
            </p>
          </div>
        </div>
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
                feed data into it — upstream producers, up to {hops} hop{hops > 1 ? "s" : ""} away. <strong>Green nodes on the right</strong>{" "}
                consume data from it — downstream reports, pipelines, and views.
                KPIs at the top count each direction. Click any node in the graph to jump
                to its own lineage.
              </>
            }
          >
          {/* KPIs */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            {/* When a direction filter hides one side, show "—" instead of
                a misleading "0" — the count isn't zero, it's just not in
                this view. The true degree still shows in Object Details. */}
            <KpiCard label="Feeds data from" value={direction === "down" ? "—" : upstreamList.length + (isSelfReferencing ? 1 : 0)} color="#DC2626" />
            <KpiCard label="Sends data to" value={direction === "up" ? "—" : downstreamList.length + (isSelfReferencing ? 1 : 0)} color="#16A34A" />
            <KpiCard label="Related objects" value={nodes.length} color="#2563EB" />
            <KpiCard label="Data flows" value={edges.length} color="#00233C" />
          </div>

          {/* Lineage graph */}
          {nodes.length > 1 ? (
            /* Outer div is `relative` (no overflow-clip) so the popup can
               render as an absolute child without being clipped. The inner
               div clips the ReactFlow canvas at the rounded border. */
            <div
              ref={graphContainerRef}
              className="relative bg-white rounded-lg shadow-sm border border-gray-200 mb-4"
              style={{ height: 450 }}
            >
              <div className="absolute inset-0 overflow-hidden rounded-lg">
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  nodeTypes={nodeTypes}
                  onNodeClick={onNodeClick}
                  onEdgeClick={onEdgeClick}
                  onPaneClick={() => setClickedEdge(null)}
                  fitView
                  minZoom={0.3}
                  maxZoom={2}
                  attributionPosition="bottom-left"
                >
                  <Background gap={16} size={1} />
                  <Controls />
                </ReactFlow>
              </div>

              {/* Feature 3 — floating popup at the click position */}
              {clickedEdge && (
                <div
                  className="absolute z-50 w-72 bg-white border border-purple-300 rounded-xl shadow-2xl overflow-hidden"
                  style={{ left: clickedEdge.x, top: clickedEdge.y }}
                >
                  {/* Header */}
                  <div className="flex items-center gap-1.5 px-3 py-2 bg-purple-600">
                    <GitBranch size={11} className="text-purple-200" />
                    <span className="text-[11px] font-bold text-white flex-1">Column edge</span>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setClickedEdge(null); }}
                      className="text-purple-300 hover:text-white text-xs font-bold leading-none"
                      aria-label="Cerrar"
                    >✕</button>
                  </div>
                  {/* Column mappings */}
                  <div className="px-3 py-2 space-y-0.5 max-h-28 overflow-y-auto border-b border-purple-100">
                    {clickedEdge.labels.map((lbl, i) => (
                      <div key={i} className="font-mono text-[9px] text-purple-900 bg-purple-50 rounded px-1.5 py-0.5">
                        {lbl}
                      </div>
                    ))}
                  </div>
                  {/* Step IDs */}
                  <div className="px-3 py-2 bg-gray-50">
                    <p className="text-[8px] font-bold text-purple-400 uppercase tracking-widest mb-1">
                      SQL step{clickedEdge.steps.length !== 1 ? "s" : ""}
                    </p>
                    {clickedEdge.steps.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {clickedEdge.steps.map((s) => (
                          <span key={s} className="font-mono text-[9px] bg-purple-100 text-purple-800 rounded px-1.5 py-0.5 border border-purple-200">
                            {s}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[9px] text-gray-400 italic">No step ID recorded.</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-8 text-center text-sm text-td-gray-dark mb-6">
              <Network size={32} className="mx-auto mb-2 opacity-30" />
              No direct data relationships found for this object. Try selecting a table that references other tables.
            </div>
          )}

          {/* Legend */}
          <div className="flex items-center gap-6 text-xs text-td-gray-dark mb-6">
            <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded border-2 border-red-600 bg-red-50" /> Provides data</div>
            <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded border-2 border-blue-600 bg-blue-50" /> Selected object</div>
            <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded border-2 border-green-600 bg-green-50" /> Receives data</div>
            <div className="flex items-center gap-1.5"><span className="w-6 border-t-2 border-dashed border-blue-500" /> Data flow</div>
            {showColumnLineage && <div className="flex items-center gap-1.5"><span className="w-6 border-t-2 border-dashed border-purple-500" /> Column flow · click edge to inspect</div>}
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
                <h3 className="text-sm font-semibold text-td-upstream">Where data comes from ({upstreamList.length + (isSelfReferencing ? 1 : 0)})</h3>
              </div>
              {direction === "down" ? (
                <p className="text-xs text-td-gray-dark">Hidden — Direction filter is set to Downstream. Switch to Both or Upstream to see producers.</p>
              ) : upstreamList.length === 0 && !isSelfReferencing ? (
                <p className="text-xs text-td-gray-dark">This is a source table — data originates here.</p>
              ) : (
                <ul className="space-y-1">
                  {isSelfReferencing && (
                    <li className="text-xs font-mono bg-amber-50 rounded px-2 py-1 text-amber-800 border border-amber-200">
                      {selectedNodeData.object_name.split(".").pop()} <span className="text-amber-500 font-normal">(self-referencing)</span>
                    </li>
                  )}
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
                <h3 className="text-sm font-semibold text-td-downstream">Where data goes ({downstreamList.length + (isSelfReferencing ? 1 : 0)})</h3>
              </div>
              {direction === "up" ? (
                <p className="text-xs text-td-gray-dark">Hidden — Direction filter is set to Upstream. Switch to Both or Downstream to see consumers.</p>
              ) : downstreamList.length === 0 && !isSelfReferencing ? (
                <p className="text-xs text-td-gray-dark">This is an endpoint — no other objects consume this data directly.</p>
              ) : (
                <ul className="space-y-1">
                  {isSelfReferencing && (
                    <li className="text-xs font-mono bg-amber-50 rounded px-2 py-1 text-amber-800 border border-amber-200">
                      {selectedNodeData.object_name.split(".").pop()} <span className="text-amber-500 font-normal">(self-referencing)</span>
                    </li>
                  )}
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

          {/* ── Column-Level Lineage ── full-width row below the 3 panels */}
          {(colLineageLoading || (columnLineage && columnLineage.total_edges > 0)) && (
            <div className="mt-4 bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
              {/* Header */}
              <div className="px-4 pt-3 pb-2 border-b border-gray-100 bg-gray-50">
                <div className="flex items-center gap-2">
                  <GitBranch size={14} className="text-purple-600" />
                  <h3 className="text-sm font-semibold text-gray-700">Column-Level Lineage</h3>
                  {!colLineageLoading && columnLineage && (
                    <>
                      <span className="text-[10px] bg-purple-100 text-purple-700 rounded px-1.5 py-0.5 font-medium">
                        {columnLineage.total_edges} edges · Tier 1/2
                      </span>
                      <span className="ml-auto text-[10px] text-td-gray-dark">
                        {columnLineage.columns.length} column{columnLineage.columns.length !== 1 ? "s" : ""} mapped
                      </span>
                    </>
                  )}
                </div>
                <p className="text-[11px] text-td-gray-dark mt-1.5 leading-relaxed">
                  Finer-grained view of <strong>which specific columns feed which</strong>, derived from the DataDNA parser
                  Tier&nbsp;1/2 output. <strong>Red cards</strong> show where each column&apos;s value originates (sources);{" "}
                  <strong>green cards</strong> show which downstream columns it populates (consumers). The transformation
                  type — <em>Direct Copy</em>, <em>Aggregate</em>, <em>Type Cast</em>, etc. — describes how the value
                  changes in transit.
                </p>
              </div>

              {/* Body */}
              {colLineageLoading ? (
                <div className="px-4 py-6 text-xs text-td-gray-dark">Loading column mappings…</div>
              ) : columnLineage && columnLineage.columns.length > 0 ? (
                <div className="p-4 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
                  {columnLineage.columns.map((col) => (
                    <div key={col.column_name} className="rounded-lg border border-gray-200 overflow-hidden text-xs shadow-sm">
                      {/* Column name pill */}
                      <div className="bg-gray-800 px-3 py-2">
                        <span className="font-mono font-bold text-white text-[11px] truncate block" title={col.column_name}>
                          {col.column_name}
                        </span>
                      </div>

                      {/* Sources (upstream → this column) */}
                      {col.upstream.length > 0 && (
                        <div className="bg-red-50 px-3 py-2 border-b border-red-100">
                          <div className="text-[9px] font-bold text-red-400 uppercase tracking-widest mb-1.5">Sources</div>
                          <div className="space-y-1">
                            {col.upstream.map((e, i) => (
                              <div key={i} className="flex items-center justify-between gap-1.5">
                                <span className="font-mono text-[10px] text-red-900 truncate" title={e.column_key}>
                                  <span className="text-red-400">{e.table_key.split(".").pop()}.</span>{e.column_name}
                                </span>
                                <TransformBadge
                                  type={e.transformation_type}
                                  className="text-[10px] bg-red-100 text-red-600 rounded px-1 py-0.5"
                                />
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Feeds into (this column → downstream) */}
                      {col.downstream.length > 0 && (
                        <div className={`bg-green-50 px-3 py-2${col.indirect?.length > 0 ? " border-b border-green-100" : ""}`}>
                          <div className="text-[9px] font-bold text-green-500 uppercase tracking-widest mb-1.5">Feeds into</div>
                          <div className="space-y-1">
                            {col.downstream.map((e, i) => (
                              <div key={i} className="flex items-center justify-between gap-1.5">
                                <span className="font-mono text-[10px] text-green-900 truncate" title={e.column_key}>
                                  <span className="text-green-500">{e.table_key.split(".").pop()}.</span>{e.column_name}
                                </span>
                                <TransformBadge
                                  type={e.transformation_type}
                                  className="text-[10px] bg-green-100 text-green-700 rounded px-1 py-0.5"
                                />
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Indirect impacts (filter / join conditions, no target column) */}
                      {col.indirect?.length > 0 && (
                        <IndirectSection
                          indirect={col.indirect}
                          expanded={expandedIndirect === col.column_name}
                          onToggle={() =>
                            setExpandedIndirect((prev) =>
                              prev === col.column_name ? null : col.column_name
                            )
                          }
                        />
                      )}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          )}
          </GuidedSection>
        </>
      )}
    </PageShell>
  );
}
