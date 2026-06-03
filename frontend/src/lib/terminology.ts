/**
 * Centralized terminology for SCION UI.
 *
 * Internally, the backend uses "schema" (compatible with SQLite/PostgreSQL)
 * and common object types like TABLE, VIEW. In Teradata the equivalent
 * concept of a "schema" is a "database", and there are more object types
 * (stored procedures, macros, UDFs, triggers, etc.). This module maps
 * internal identifiers to user-facing labels.
 *
 * Keep this file as the SINGLE SOURCE OF TRUTH for labels shown to users.
 */

// Database vs schema wording (Teradata-style)
export const LABEL_DATABASE_SINGULAR = "Database";
export const LABEL_DATABASE_PLURAL = "Databases";
export const LABEL_DATABASE_LOWER = "database";
export const LABEL_DATABASE_LOWER_PLURAL = "databases";

// Full set of supported object types. Backend may send any string; unknown
// types fall back to a neutral style.
export const OBJECT_TYPES = [
  "DATABASE",
  "SCHEMA",              // legacy alias for DATABASE — rendered the same way
  "TABLE",
  "VIEW",
  "STORED_PROCEDURE",
  "MACRO",
  "FUNCTION",
  "UDF",
  "TRIGGER",
  "INDEX",
  "SEQUENCE",
  "COLUMN",
] as const;

export type ObjectType = typeof OBJECT_TYPES[number];

/** Human-readable label for an object type (short form). */
export function objectTypeLabel(type: string): string {
  const map: Record<string, string> = {
    DATABASE: "Database",
    SCHEMA: "Database",           // render schemas as Database in Teradata context
    TABLE: "Table",
    VIEW: "View",
    STORED_PROCEDURE: "Stored Procedure",
    MACRO: "Macro",
    FUNCTION: "Function",
    UDF: "UDF",
    TRIGGER: "Trigger",
    INDEX: "Index",
    SEQUENCE: "Sequence",
    COLUMN: "Column",
  };
  return map[type] ?? type;
}

/** Short abbreviation (for badges, icons). */
export function objectTypeAbbrev(type: string): string {
  const map: Record<string, string> = {
    DATABASE: "DB",
    SCHEMA: "DB",
    TABLE: "T",
    VIEW: "V",
    STORED_PROCEDURE: "SP",
    MACRO: "M",
    FUNCTION: "F",
    UDF: "U",
    TRIGGER: "TR",
    INDEX: "I",
    SEQUENCE: "SQ",
    COLUMN: "C",
  };
  return map[type] ?? "?";
}

/** Colour palette for object types — consistent across Graph, Lineage, badges. */
export const OBJECT_TYPE_STYLES: Record<string, { bg: string; accent: string; text: string }> = {
  DATABASE:         { bg: "#EFF6FF", accent: "#3B82F6", text: "#1E40AF" }, // blue
  SCHEMA:           { bg: "#EFF6FF", accent: "#3B82F6", text: "#1E40AF" },
  TABLE:            { bg: "#F0FDF4", accent: "#22C55E", text: "#166534" }, // green
  VIEW:             { bg: "#FFF7ED", accent: "#F97316", text: "#9A3412" }, // orange
  STORED_PROCEDURE: { bg: "#F5F3FF", accent: "#8B5CF6", text: "#5B21B6" }, // purple
  MACRO:            { bg: "#FDF4FF", accent: "#D946EF", text: "#86198F" }, // fuchsia
  FUNCTION:         { bg: "#ECFEFF", accent: "#06B6D4", text: "#155E75" }, // cyan
  UDF:              { bg: "#ECFEFF", accent: "#06B6D4", text: "#155E75" },
  TRIGGER:          { bg: "#FEF2F2", accent: "#EF4444", text: "#991B1B" }, // red
  INDEX:            { bg: "#FEFCE8", accent: "#EAB308", text: "#854D0E" }, // yellow
  SEQUENCE:         { bg: "#F0FDFA", accent: "#14B8A6", text: "#115E59" }, // teal
  COLUMN:           { bg: "#F9FAFB", accent: "#9CA3AF", text: "#374151" }, // grey
};

export const DEFAULT_OBJECT_STYLE = { bg: "#F9FAFB", accent: "#9CA3AF", text: "#374151" };

/** Get the style for an object type, with fallback. */
export function getObjectTypeStyle(type: string) {
  return OBJECT_TYPE_STYLES[type] ?? DEFAULT_OBJECT_STYLE;
}

// ──── "Breaking" change vocabulary ────
// The `is_breaking` flag confused testers in end-user testing (Reunion
// 11): a red "BREAKING" badge with no guidance on what it means or what
// to do about it. We keep the industry-standard word "Breaking" but
// centralise the explanation here so every surface (Changes, Impact,
// Alerts, Home) shows the same meaning + the expected tester action.
export const BREAKING_LABEL = "Breaking";

/** One-liner shown as a hover title directly on the badge. */
export const BREAKING_MEANING =
  "This change can break downstream objects that depend on it — e.g. a " +
  "dropped or retyped column used by a view, report, or query.";

/** What a tester should do — shown as the InfoTooltip detail line. */
export const BREAKING_TESTER_ACTION =
  "It's a risk flag, not a confirmed failure. When testing, review the " +
  "impacted downstream objects (see Impact detail) and verify whether any " +
  "actually break, then report those.";

/**
 * Why THIS specific change is flagged breaking. `is_breaking` is derived
 * purely from the change type (backend `BREAKING_CHANGES` set), so the
 * reason is deterministic from the type — and we sharpen it with the
 * before/after state (e.g. the old/new column type) when available.
 * Falls back to the generic meaning for any unmapped type.
 */
export function breakingReason(
  changeType: string,
  before?: Record<string, unknown> | null,
  after?: Record<string, unknown> | null,
): string {
  const beforeType =
    before && typeof before.data_type === "string" ? before.data_type : null;
  const afterType =
    after && typeof after.data_type === "string" ? after.data_type : null;

  switch (changeType) {
    case "COLUMN_REMOVED":
      return (
        `This column was removed${beforeType ? ` (was ${beforeType})` : ""}. ` +
        "Any view, report, or query that selects it will fail."
      );
    case "COLUMN_TYPE_CHANGED":
      return (
        "This column's type changed" +
        (beforeType && afterType ? ` from ${beforeType} to ${afterType}` : "") +
        ". Consumers that expect the old type — casts, joins, parsing — may break."
      );
    case "TABLE_REMOVED":
      return (
        "This table was removed. Every view, report, or query that reads " +
        "from it breaks until they're repointed or dropped."
      );
    case "TABLE_TYPE_CHANGED":
      return (
        "This object's type changed (e.g. table ↔ view). Consumers built " +
        "against the previous kind may break."
      );
    case "SCHEMA_REMOVED":
      return (
        "This database was removed. All objects under it — and their " +
        "downstream consumers — break."
      );
    default:
      return BREAKING_MEANING;
  }
}

/**
 * For a change event, returns a short human-readable description.
 */
export function changeTypeLabel(changeType: string): string {
  const map: Record<string, string> = {
    SCHEMA_ADDED: "Database added",
    SCHEMA_REMOVED: "Database removed",
    DATABASE_ADDED: "Database added",
    DATABASE_REMOVED: "Database removed",
    TABLE_ADDED: "Table added",
    TABLE_REMOVED: "Table removed",
    TABLE_TYPE_CHANGED: "Table type changed",
    COLUMN_ADDED: "Column added",
    COLUMN_REMOVED: "Column removed",
    COLUMN_TYPE_CHANGED: "Column type changed",
    COLUMN_NULLABILITY_CHANGED: "Nullability changed",
    COLUMN_POSITION_CHANGED: "Column position changed",
    STORED_PROCEDURE_ADDED: "Stored procedure added",
    STORED_PROCEDURE_REMOVED: "Stored procedure removed",
    STORED_PROCEDURE_CHANGED: "Stored procedure changed",
    MACRO_ADDED: "Macro added",
    MACRO_REMOVED: "Macro removed",
    MACRO_CHANGED: "Macro changed",
    FUNCTION_ADDED: "Function added",
    FUNCTION_REMOVED: "Function removed",
    FUNCTION_CHANGED: "Function changed",
    TRIGGER_ADDED: "Trigger added",
    TRIGGER_REMOVED: "Trigger removed",
    INDEX_ADDED: "Index added",
    INDEX_REMOVED: "Index removed",
  };
  return map[changeType] ?? changeType.replace(/_/g, " ").toLowerCase();
}
