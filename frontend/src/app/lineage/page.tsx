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

/* ---- Custom nodes for the lineage subgraph ---- */
function UpstreamNode({ data }: { data: { label: string; type: string; metrics?: GN["metrics"] } }) {
  return (
    <div style={{ background: "#FEF2F2", border: "2px solid #DC2626", borderRadius: 10, padding: "8px 12px", width: NODE_W, cursor: "pointer" }}>
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
    <div style={{ background: "#EFF6FF", border: "3px solid #2563EB", borderRadius: 12, padding: "10px 14px", width: NODE_W, boxShadow: "0 4px 12px rgba(37,99,235,0.2)", cursor: "default" }}>
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
    <div style={{ background: "#F0FDF4", border: "2px solid #16A34A", borderRadius: 10, padding: "8px 12px", width: NODE_W, cursor: "pointer" }}>
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
    const request: Promise<FocusedGraphResponse> =
      direction === "both"
        ? Promise.all([
            getFocusedGraph({ ...base, direction: "up" }),
            getFocusedGraph({ ...base, direction: "down" }),
          ]).then(([up, down]) => mergeFocusedGraphs(up, down))
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

    // Generalised N-hop BFS over FEEDS edges. We walk upstream (follow
    // edges backwards: a node that feeds the frontier) and downstream
    // (follow edges forwards: a node fed by the frontier) to whatever
    // depth the focus call returned, tagging each reachable node with
    // its direction and 1-based hop distance from the root. This
    // replaces the old hard-coded 2-level tagging so the depth stepper
    // can render 1..5 levels in each direction.
    const feedsEdges = focusData.edges.filter((e) => e.type === "FEEDS");
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

    const laidOut = layoutNodes(rfNodes, rfEdges);

    // The side lists keep their "immediate producers / consumers"
    // meaning: only depth-1 neighbours, no matter how deep the graph
    // now goes.
    const directNeighbours = (dir: "upstream" | "downstream") =>
      [...direction.entries()]
        .filter(([id, d]) => d === dir && depthOf.get(id) === 1)
        .map(([id]) => nodeMap.get(id)?.object_name ?? id);

    return {
      nodes: laidOut,
      edges: rfEdges,
      upstreamList: directNeighbours("upstream"),
      downstreamList: directNeighbours("downstream"),
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
            <KpiCard label="Feeds data from" value={direction === "down" ? "—" : upstreamList.length} color="#DC2626" />
            <KpiCard label="Sends data to" value={direction === "up" ? "—" : downstreamList.length} color="#16A34A" />
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
                onNodeClick={onNodeClick}
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
              {direction === "down" ? (
                <p className="text-xs text-td-gray-dark">Hidden — Direction filter is set to Downstream. Switch to Both or Upstream to see producers.</p>
              ) : upstreamList.length === 0 ? (
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
              {direction === "up" ? (
                <p className="text-xs text-td-gray-dark">Hidden — Direction filter is set to Upstream. Switch to Both or Downstream to see consumers.</p>
              ) : downstreamList.length === 0 ? (
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
