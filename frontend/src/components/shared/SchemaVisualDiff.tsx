"use client";

import { useState, useEffect, useMemo } from "react";
import client from "@/lib/api/client";
import type { DiffDetailItem } from "@/lib/api/types";
import { Database, Table2, Columns3, Plus, Minus, RefreshCw, ChevronDown, ChevronRight, ArrowRightLeft } from "lucide-react";
import { changeTypeLabel } from "@/lib/terminology";

interface Column {
  column_name: string;
  data_type: string;
  nullable: boolean;
  ordinal_position: number;
}

interface TableDef {
  table_name: string;
  object_type: string;
  columns: Column[];
}

interface Schema {
  schema_name: string;
  tables: TableDef[];
}

interface SchemaTree {
  snapshot_id: number;
  schemas: Schema[];
}

type DiffStatus = "added" | "removed" | "modified" | "unchanged";

interface Props {
  snapshotFrom: number;
  snapshotTo: number;
  changes: DiffDetailItem[];
}

const STATUS_STYLES: Record<DiffStatus, { bg: string; border: string; text: string }> = {
  added:     { bg: "#dcfce7", border: "#22c55e", text: "#15803d" },
  removed:   { bg: "#fee2e2", border: "#ef4444", text: "#b91c1c" },
  modified:  { bg: "#fef9c3", border: "#eab308", text: "#a16207" },
  unchanged: { bg: "#f8fafc", border: "#e2e8f0", text: "#334155" },
};

const STATUS_BADGE: Record<DiffStatus, { label: string; bg: string } | null> = {
  added:     { label: "NEW",      bg: "#16a34a" },
  removed:   { label: "REMOVED",  bg: "#dc2626" },
  modified:  { label: "CHANGED",  bg: "#d97706" },
  unchanged: null,
};

// Map change_type to visual diff status
function changeTypeToStatus(changeType: string): DiffStatus {
  switch (changeType) {
    case "TABLE_ADDED":
    case "COLUMN_ADDED":
    case "SCHEMA_ADDED":
      return "added";
    case "TABLE_REMOVED":
    case "COLUMN_REMOVED":
    case "SCHEMA_REMOVED":
      return "removed";
    default:
      return "modified";
  }
}

/**
 * SchemaVisualDiff — renders the "to" snapshot's schema tree and overlays
 * diff status (added / removed / modified / unchanged) from the change list.
 *
 * Rendering strategy: we fetch only the "to" snapshot tree and synthesize
 * removed schemas/tables/columns from the change events (since they no
 * longer exist in the live tree). This avoids a second round-trip and lets
 * the component work from any upstream diff source.
 */
export default function SchemaVisualDiff({ snapshotFrom, snapshotTo, changes }: Props) {
  const [treeTo, setTreeTo] = useState<SchemaTree | null>(null);
  // fullTreeLoading: true only while an explicit "load full tree" request is
  // in progress. We no longer auto-fetch the tree on mount — for large
  // snapshots (240k+ tables) that blocked the view for minutes.
  const [fullTreeLoading, setFullTreeLoading] = useState(false);
  const [expandedSchemas, setExpandedSchemas] = useState<Set<string>>(new Set());
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set());
  const [filterStatus, setFilterStatus] = useState<DiffStatus | "all">("all");

  // Build change lookup from the real diff results.
  // Memoized so we don't rebuild the three Maps on every render — the only
  // input that matters is `changes`, which typically changes only on new diff.
  // The resulting Maps are keyed by fully-qualified name so lookups by the
  // tree walker below are O(1).
  const changeLookup = useMemo(() => {
    const bySchema = new Map<string, DiffStatus>();
    const byTable = new Map<string, { status: DiffStatus; changeType: string; severity: string; isBreaking: boolean }>();
    const byColumn = new Map<string, { status: DiffStatus; changeType: string; before: Record<string, unknown> | null; after: Record<string, unknown> | null }>();

    for (const c of changes) {
      const parts = c.object_identifier.split(".");
      const schema = parts[0];
      const table = parts.length >= 2 ? `${parts[0]}.${parts[1]}` : null;
      const column = parts.length >= 3 ? c.object_identifier : null;
      const status = changeTypeToStatus(c.change_type);

      // Schema level
      if (c.object_type === "SCHEMA") {
        bySchema.set(schema, status);
      }

      // Table level
      if (c.object_type === "TABLE" && table) {
        byTable.set(table, { status, changeType: c.change_type, severity: c.severity ?? "LOW", isBreaking: c.is_breaking ?? false });
      }

      // Column level. When a column changes but the parent table has no
      // direct change entry, we still want the table to render as "modified"
      // so the user sees the affected row. The HAS_COLUMN_CHANGES sentinel
      // lets the UI know this status was inferred, not explicit.
      if (c.object_type === "COLUMN" && column) {
        byColumn.set(column, { status, changeType: c.change_type, before: c.before_state, after: c.after_state });
        // Also mark parent table as modified if not already marked with something stronger
        if (table && !byTable.has(table)) {
          byTable.set(table, { status: "modified", changeType: "HAS_COLUMN_CHANGES", severity: c.severity ?? "LOW", isBreaking: c.is_breaking ?? false });
        }
      }
    }

    return { bySchema, byTable, byColumn };
  }, [changes]);

  // Auto-expand changed schemas as soon as changes are known — no tree needed.
  useEffect(() => {
    const changed = new Set<string>();
    for (const key of changeLookup.byTable.keys()) changed.add(key.split(".")[0]);
    for (const key of changeLookup.bySchema.keys()) changed.add(key);
    setExpandedSchemas(changed);
    setExpandedTables(new Set());
  }, [changeLookup]);

  // Optional: load the full schema tree so unchanged objects also appear.
  // Not triggered automatically — for large snapshots (240k+ tables) this
  // blocked the view for several minutes. The user opts in via the button below.
  function handleLoadFullTree() {
    setFullTreeLoading(true);
    client.get<SchemaTree>(`/schema-tree/${snapshotTo}`)
      .then((res) => { setTreeTo(res.data); })
      .catch(() => {})
      .finally(() => setFullTreeLoading(false));
  }

  // Build the display tree. When `treeTo` is available we use the full tree
  // (unchanged objects + changed overlaid). When it's null we build from
  // `changeLookup` alone (changed objects only — instant, no network call).
  function getSchemaStatus(schemaName: string): DiffStatus {
    return changeLookup.bySchema.get(schemaName) ?? "unchanged";
  }
  function getTableChange(schemaName: string, tableName: string) {
    return changeLookup.byTable.get(`${schemaName}.${tableName}`);
  }
  function getColumnChange(schemaName: string, tableName: string, colName: string) {
    return changeLookup.byColumn.get(`${schemaName}.${tableName}.${colName}`);
  }
  function getColumnStatus(schemaName: string, tableName: string, colName: string): DiffStatus {
    return changeLookup.byColumn.get(`${schemaName}.${tableName}.${colName}`)?.status ?? "unchanged";
  }

  const counts = { added: 0, removed: 0, modified: 0, unchanged: 0 };
  const enrichedSchemas: { name: string; status: DiffStatus; tables: { name: string; type: string; status: DiffStatus; columns: Column[] }[] }[] = [];

  if (treeTo) {
    // ── Full-tree mode (user loaded the tree): show unchanged objects too ──
    const existingSchemaNames = new Set(treeTo.schemas.map(s => s.schema_name));
    for (const schema of treeTo.schemas) {
      const sStatus = getSchemaStatus(schema.schema_name);
      const tables: typeof enrichedSchemas[0]["tables"] = [];
      const existingTableNames = new Set(schema.tables.map(t => t.table_name));
      for (const table of schema.tables) {
        const tStatus = changeLookup.byTable.get(`${schema.schema_name}.${table.table_name}`)?.status ?? "unchanged";
        if (tStatus !== "unchanged") counts[tStatus]++; else counts.unchanged++;
        tables.push({ name: table.table_name, type: table.object_type, status: tStatus, columns: table.columns });
      }
      for (const [key, val] of changeLookup.byTable) {
        const [s, t] = key.split(".");
        if (s === schema.schema_name && !existingTableNames.has(t) && val.status === "removed") {
          counts.removed++;
          tables.push({ name: t, type: "TABLE", status: "removed", columns: [] });
        }
      }
      enrichedSchemas.push({ name: schema.schema_name, status: sStatus, tables });
    }
    for (const [schemaName, status] of changeLookup.bySchema) {
      if (!existingSchemaNames.has(schemaName) && status === "removed") {
        enrichedSchemas.push({ name: schemaName, status: "removed", tables: [] });
      }
    }
  } else {
    // ── Changes-only mode (default): build purely from changeLookup ──
    // Groups changes by schema so we can render them without the full tree.
    const schemaMap = new Map<string, typeof enrichedSchemas[0]["tables"]>();
    for (const [tableKey, val] of changeLookup.byTable) {
      const [schemaName, tableName] = tableKey.split(".");
      if (!schemaMap.has(schemaName)) schemaMap.set(schemaName, []);
      schemaMap.get(schemaName)!.push({ name: tableName, type: "TABLE", status: val.status, columns: [] });
      counts[val.status]++;
    }
    for (const [schemaName, status] of changeLookup.bySchema) {
      if (!schemaMap.has(schemaName)) schemaMap.set(schemaName, []);
      // schema-level changes that may have no table entries
    }
    for (const [name, tables] of schemaMap) {
      enrichedSchemas.push({ name, status: getSchemaStatus(name), tables });
    }
    enrichedSchemas.sort((a, b) => a.name.localeCompare(b.name));
  }

  const totalAll = counts.added + counts.removed + counts.modified + counts.unchanged;

  function toggleSchema(name: string) {
    setExpandedSchemas((prev) => { const n = new Set(prev); n.has(name) ? n.delete(name) : n.add(name); return n; });
  }
  function toggleTable(key: string) {
    setExpandedTables((prev) => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  }

  return (
    <div>
      {/* Summary bar */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <span className="text-xs font-semibold" style={{ color: "#334155" }}>
          #{snapshotFrom} → #{snapshotTo} ({changes.length} changes shown):
        </span>
        {[
          { key: "all" as const, label: "All", count: totalAll, color: "#64748b" },
          { key: "added" as const, label: "New", count: counts.added, color: "#16a34a" },
          { key: "removed" as const, label: "Removed", count: counts.removed, color: "#dc2626" },
          { key: "modified" as const, label: "Changed", count: counts.modified, color: "#d97706" },
          ...(treeTo ? [{ key: "unchanged" as const, label: "Unchanged", count: counts.unchanged, color: "#94a3b8" }] : []),
        ].map((f) => (
          <button
            key={f.key}
            onClick={() => setFilterStatus(f.key)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all"
            style={{
              backgroundColor: filterStatus === f.key ? f.color : "transparent",
              color: filterStatus === f.key ? "white" : f.color,
              border: `1.5px solid ${f.color}`,
            }}
          >
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: filterStatus === f.key ? "white" : f.color }} />
            {f.label} ({f.count})
          </button>
        ))}
        {/* "Load full tree" opt-in — skipped by default to avoid the
            multi-minute wait on large snapshots (240k+ tables). */}
        {!treeTo && (
          <button
            onClick={handleLoadFullTree}
            disabled={fullTreeLoading}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border border-gray-300 text-td-gray-dark hover:bg-gray-50 disabled:opacity-50 transition-all"
          >
            {fullTreeLoading
              ? <><RefreshCw size={11} className="animate-spin" /> Loading full tree…</>
              : <><RefreshCw size={11} /> Load full tree (includes unchanged)</>}
          </button>
        )}
      </div>

      {/* Schema tree */}
      <div className="space-y-3">
        {enrichedSchemas.map(({ name: schemaName, status: schemaStatus, tables }) => {
          const isExpanded = expandedSchemas.has(schemaName);
          const ss = STATUS_STYLES[schemaStatus];
          const badge = STATUS_BADGE[schemaStatus];

          const visibleTables = filterStatus === "all"
            ? tables
            : tables.filter((t) => t.status === filterStatus);

          if (filterStatus !== "all" && visibleTables.length === 0 && schemaStatus !== filterStatus) return null;

          const changedCount = tables.filter(t => t.status !== "unchanged").length;

          return (
            <div key={schemaName} className="rounded-xl overflow-hidden" style={{ border: `2px solid ${ss.border}`, backgroundColor: ss.bg }}>
              <button
                onClick={() => toggleSchema(schemaName)}
                className="w-full flex items-center gap-3 px-5 py-3 text-left transition-colors hover:brightness-95"
              >
                {isExpanded ? <ChevronDown size={16} style={{ color: ss.text }} /> : <ChevronRight size={16} style={{ color: ss.text }} />}
                <Database size={16} style={{ color: ss.text }} />
                <span className="text-base font-bold" style={{ color: ss.text }}>{schemaName}</span>
                <span className="text-xs" style={{ color: "#64748b" }}>
                  {changedCount > 0
                    ? `(${changedCount} of ${tables.length} tables changed)`
                    : `(${tables.length} tables, no changes)`}
                </span>
                {badge && (
                  <span className="ml-auto text-[10px] text-white px-2 py-0.5 rounded-full font-bold" style={{ backgroundColor: badge.bg }}>
                    {badge.label}
                  </span>
                )}
              </button>

              {isExpanded && visibleTables.length > 0 && (
                <div className="px-5 pb-4 space-y-2">
                  {visibleTables.map((table) => {
                    const tblKey = `${schemaName}.${table.name}`;
                    const tblExpanded = expandedTables.has(tblKey);
                    const ts = STATUS_STYLES[table.status];
                    const tBadge = STATUS_BADGE[table.status];
                    const tChange = getTableChange(schemaName, table.name);

                    // Build column list with removed columns from changes.
                    // Same pattern as schemas/tables: we start from what
                    // exists in the "to" snapshot and splice in removed
                    // columns reconstructed from the change's before_state.
                    const existingCols = new Set(table.columns.map(c => c.column_name));
                    const allCols = [...table.columns];

                    // Add removed columns that aren't in current tree
                    for (const [key, val] of changeLookup.byColumn) {
                      const parts = key.split(".");
                      if (parts[0] === schemaName && parts[1] === table.name && parts[2] && !existingCols.has(parts[2]) && val.status === "removed") {
                        allCols.push({
                          column_name: parts[2],
                          data_type: (val.before as any)?.data_type ?? "?",
                          nullable: (val.before as any)?.nullable ?? true,
                          ordinal_position: 999,
                        });
                      }
                    }

                    const changedCols = allCols.filter(c => getColumnStatus(schemaName, table.name, c.column_name) !== "unchanged").length;

                    return (
                      <div key={table.name} className="rounded-lg overflow-hidden ml-3" style={{ border: `1.5px solid ${ts.border}`, backgroundColor: ts.bg }}>
                        <button
                          onClick={() => toggleTable(tblKey)}
                          className="w-full flex items-center gap-2.5 px-4 py-2.5 text-left transition-colors hover:brightness-95"
                        >
                          {tblExpanded ? <ChevronDown size={13} style={{ color: ts.text }} /> : <ChevronRight size={13} style={{ color: ts.text }} />}
                          <Table2 size={13} style={{ color: ts.text }} />
                          <span className="text-sm font-semibold" style={{ color: ts.text }}>{table.name}</span>
                          <span className="text-[11px] font-mono px-1.5 py-0.5 rounded" style={{ backgroundColor: `${ts.border}20`, color: ts.text }}>
                            {table.type}
                          </span>
                          <span className="text-[11px]" style={{ color: "#64748b" }}>
                            {allCols.length} cols{changedCols > 0 ? ` (${changedCols} changed)` : ""}
                          </span>
                          {tChange && tChange.changeType !== "HAS_COLUMN_CHANGES" && (
                            <span
                              className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                              style={{ backgroundColor: "#f1f5f9", color: "#475569" }}
                              title={tChange.changeType}
                            >
                              {changeTypeLabel(tChange.changeType)}
                            </span>
                          )}
                          {tBadge && (
                            <span className="ml-auto text-[9px] text-white px-2 py-0.5 rounded-full font-bold" style={{ backgroundColor: tBadge.bg }}>
                              {tBadge.label}
                            </span>
                          )}
                        </button>

                        {tblExpanded && allCols.length > 0 && (
                          <div className="px-4 pb-3 space-y-1 ml-6">
                            {allCols.map((col) => {
                              const colStatus = getColumnStatus(schemaName, table.name, col.column_name);
                              const cs = STATUS_STYLES[colStatus];
                              const cBadge = STATUS_BADGE[colStatus];
                              const cChange = getColumnChange(schemaName, table.name, col.column_name);

                              return (
                                <div
                                  key={col.column_name}
                                  className="flex items-center gap-2 px-3 py-1.5 rounded-md"
                                  style={{ border: `1px solid ${cs.border}`, backgroundColor: cs.bg }}
                                >
                                  {colStatus === "added" && <Plus size={11} style={{ color: "#16a34a" }} />}
                                  {colStatus === "removed" && <Minus size={11} style={{ color: "#dc2626" }} />}
                                  {colStatus === "modified" && <ArrowRightLeft size={11} style={{ color: "#d97706" }} />}
                                  {colStatus === "unchanged" && <Columns3 size={11} style={{ color: "#94a3b8" }} />}
                                  <span className="text-xs font-mono font-semibold" style={{ color: cs.text }}>{col.column_name}</span>
                                  <span className="text-xs font-mono" style={{ color: "#64748b" }}>{col.data_type}</span>
                                  {!col.nullable && (
                                    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded" style={{ backgroundColor: "#fef2f2", color: "#dc2626", border: "1px solid #fecaca" }}>
                                      NOT NULL
                                    </span>
                                  )}
                                  {/* Show before→after for modified columns */}
                                  {colStatus === "modified" && cChange?.before && cChange?.after && (
                                    <span className="text-[9px] ml-auto font-mono flex items-center gap-1" style={{ color: "#d97706" }}>
                                      {(cChange.before as any).data_type ?? "?"} → {(cChange.after as any).data_type ?? "?"}
                                    </span>
                                  )}
                                  {/* Show change type label */}
                                  {cChange && (
                                    <span
                                      className="text-[9px] font-mono px-1 py-0.5 rounded"
                                      style={{ backgroundColor: `${cs.border}15`, color: cs.text }}
                                      title={cChange.changeType}
                                    >
                                      {changeTypeLabel(cChange.changeType)}
                                    </span>
                                  )}
                                  {cBadge && !cChange?.before && (
                                    <span className="ml-auto text-[8px] text-white px-1.5 py-0.5 rounded-full font-bold" style={{ backgroundColor: cBadge.bg }}>
                                      {cBadge.label}
                                    </span>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
