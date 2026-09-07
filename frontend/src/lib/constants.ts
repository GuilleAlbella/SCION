// App-wide constants. Keep this file pure data — no React, no side effects —
// so it can be imported from both client and server components.

/** Single source of truth for the user-facing app version.
 * Bump this on every release and the Sidebar footer + home hero pill
 * update automatically. README.md still has to be bumped separately
 * (it lives outside the frontend bundle). */
export const APP_VERSION = "v2.09.15";
export const APP_STAGE = "BETA"; // "BETA" | "RC" | "" when GA

/** Internal SCION objects to filter out from graph/impact visualizations.
 * These are SCION's own metadata tables (snapshots, change events, etc.)
 * which would otherwise pollute the user-facing schema graph. */
export const INTERNAL_OBJECT_NAMES = new Set([
  "snapshot",
  "schema_snapshot",
  "table_snapshot",
  "column_snapshot",
  "change_event",
  "graph_node",
  "graph_edge",
  "impact_event",
  "reasoning_event",
  "alembic_version",
  "usage_event",
  "object_criticality",
]);

/** Color palette for donut charts. */
export const CHART_COLORS = [
  "#00233C", // td-navy
  "#0D7377", // teal
  "#2563EB", // blue
  "#38BDF8", // light blue
  "#F37440", // orange
  "#DC2626", // red
  "#7C8185", // gray
  "#16A34A", // green
];

/** Color map for impact directions. Red "upstream" = things this object
 * depends on (upstream breaks = this breaks). Green "downstream" = things
 * that depend on this object. Blue "object" = the change itself. */
export const IMPACT_COLORS = {
  upstream: "#DC2626",
  downstream: "#16A34A",
  object: "#2563EB",
};
