export interface HealthResponse {
  status: "ready" | "degraded" | "initialising";
  database: string;
  snapshot: string;
  diff: string;
  graph: string;
  taisa: string;
}

export interface Snapshot {
  snapshot_id: string;
  created_at: string;
  source_system: string;
  description: string;
  /** §2.16 Staging Layer: pending | staged | committed | failed */
  import_status?: string;
  /** §2.13 Manifest Timestamps: when the extractor ran on the client (UTC ISO string, NULL for parser/demo) */
  extract_timestamp?: string | null;
  /** §2.2 Incremental Loading: true for day-zero baselines and gap resets */
  is_baseline?: boolean;
  /** §2.2 Incremental Loading: snapshot_id of the day-zero baseline (null for baselines) */
  baseline_snapshot_id?: number | null;
  /** §2.2 Incremental Loading: true when a gap in extracts triggered a new baseline */
  gap_detected?: boolean;
  /** §2.2 Incremental Loading: distinct objects across baseline ∪ this snapshot */
  cumulative_object_count?: number | null;
}

export interface SnapshotsResponse {
  snapshots: Snapshot[];
}

export interface SnapshotDetail {
  snapshot_id: number;
  databases: number;
  tables: number;
  columns: number;
  indices: number;
  partitioning: number;
  graph_nodes: number;
  graph_edges: number;
  changes: number;
  usage_events: number;
}

export interface ChangeItem {
  change_id: number;
  object_type: string;
  object_name: string;
  change_type: string;
  snapshot_from: number;
  snapshot_to: number;
  severity: string | null;
  is_breaking: boolean | null;
  created_at: string;
}

export interface DiffDetailItem {
  change_id: number;
  object_type: string;
  object_identifier: string;
  change_type: string;
  severity: string | null;
  is_breaking: boolean | null;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  snapshot_from: number;
  snapshot_to: number;
  detected_at: string;
}

export interface DiffDetailSummary {
  total: number;
  breaking_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
}

export interface DiffDetailResponse {
  snapshot_from: number;
  snapshot_to: number;
  summary: DiffDetailSummary;
  /** Current page of changes — at most `limit` rows. The KPI cards drive
   *  off `summary` (total over the FULL filtered set), not this array. */
  changes: DiffDetailItem[];
  limit: number;
  offset: number;
  has_more: boolean;
}

/** Filter / pagination params for `getDiffDetails`. All optional — the
 *  server applies sensible defaults (limit=100, offset=0, no filters). */
export interface DiffDetailsParams {
  limit?: number;
  offset?: number;
  /** "HIGH" / "MEDIUM" / "LOW", or omit to disable. */
  severity?: string;
  /** true = breaking only, false = non-breaking only, undefined = both. */
  is_breaking?: boolean;
  /** Case-insensitive substring filter against object_identifier. */
  object_q?: string;
}

export interface ChangesResponse {
  changes: ChangeItem[];
}

export interface DiffRequest {
  snapshot_from: string;
  snapshot_to: string;
}

export interface DiffResponse {
  snapshot_from: string;
  snapshot_to: string;
  changes_detected: number;
}

export interface NodeMetrics {
  in_degree: number;
  out_degree: number;
  fragility: number;
  is_hub: boolean;
}

export interface GraphNode {
  node_id: string;
  object_type: string;
  object_name: string;
  schema_name: string;
  metrics: NodeMetrics | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
}

export interface GraphResponse {
  snapshot_id: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** True when the snapshot's full graph exceeds the server's
   *  `FULL_GRAPH_NODE_CAP` and the response was bailed early. The
   *  `nodes` and `edges` arrays will be empty; the UI should switch
   *  to the focus-picker flow. */
  truncated?: boolean;
  /** Real node count (populated regardless of truncation). Used to
   *  surface "this graph has N nodes" in the empty-state copy. */
  total_nodes?: number;
}

export interface FocusedGraphParams {
  snapshot_id: number;
  /** "schema.object_name" — the format produced by ObjectAutocomplete
   *  with `source="graph"`. Bare `object_name` also works for legacy
   *  callers. */
  root: string;
  /** BFS depth from the root. 1–5 (server-clamped). */
  hops?: number;
  /** Hard cap on returned nodes. 10–1000 (server-clamped). */
  max_nodes?: number;
  /** Comma-separated edge type whitelist (e.g. "FEEDS,DEPENDS_ON"). */
  edge_types?: string;
  /** Traversal direction. Default `both`. */
  direction?: "up" | "down" | "both";
}

export interface FocusedGraphResponse {
  snapshot_id: number;
  root: string;
  hops: number;
  max_nodes: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** True when BFS hit `max_nodes` before exhausting `hops`. UI should
   *  surface a "increase max_nodes or narrow the search" hint. */
  capped: boolean;
}

export interface ColumnEdge {
  column_key: string;
  table_key: string;
  column_name: string;
  expression: string | null;
  transformation_type: string | null;
  tier: string | null;
  step_natural_key: string | null;
}

export interface IndirectEdge {
  source_column_key: string;
  source_column_name: string;
  transformation_type: string | null;
  expression: string | null;
}

export interface ColumnLineageEntry {
  column_name: string;
  upstream: ColumnEdge[];
  downstream: ColumnEdge[];
  indirect: IndirectEdge[];
}

export interface ColumnLineageResponse {
  object: string;
  snapshot_id: number;
  columns: ColumnLineageEntry[];
  total_edges: number;
}

export interface ImpactItem {
  object_type: string;
  object_name: string;
  impact_type: string;
  description: string;
  depth: number;
  impact_score: number;
}

export interface ImpactResponse {
  change_id: number;
  direct_impact: ImpactItem[];
  indirect_impact: ImpactItem[];
  summary: {
    direct_count: number;
    indirect_count: number;
  };
}

export interface BatchChangeImpact {
  change_id: number;
  object_identifier: string;
  change_type: string;
  severity: string;
  is_breaking: boolean;
  direct_count: number;
  indirect_count: number;
  impact_score: number;
  query_count: number;
  user_count: number;
}

export interface AffectedDatabase {
  schema_name: string;
  tables: string[];
}

export interface BatchBlastRadius {
  total_impacted_nodes: number;
  max_depth: number;
  weighted_score: number;
  affected_schemas: string[];
  /** Flat union of every grouped table — kept for backward
   *  compatibility. New UI code should prefer `affected_databases`. */
  affected_tables: string[];
  /** Pre-grouped tables-per-database (v1.19+). Renders the
   *  "Affected objects, by database" section without the
   *  O(databases × tables) client-side filter the page used to do. */
  affected_databases?: AffectedDatabase[];
}

/** One bucket on a donut/distribution chart. Server-computed over the
 *  full filtered set so donut totals match `changes_analyzed` regardless
 *  of which page of `changes` is currently loaded. */
export interface BucketCount {
  name: string;
  count: number;
}

export interface BatchImpactRequestParams {
  /** Page size for the per-change list. Default 100, server-capped at 500. */
  limit?: number;
  /** Page offset (0-based row index). */
  offset?: number;
  /** Case-insensitive substring filter on object_identifier. Aggregates/KPIs
   *  are NOT affected — they always reflect the full diff. */
  q?: string;
}

export interface BatchImpactResponse {
  snapshot_from: number;
  snapshot_to: number;
  /** Total number of changes in the diff range — independent of pagination.
   *  KPIs and donuts in the UI should source from this + `summary` so they
   *  stay accurate as the user pages through `changes`. */
  changes_analyzed: number;
  blast_radius: BatchBlastRadius;
  /** Current page of per-change rows. Length is at most `limit`. */
  changes: BatchChangeImpact[];
  summary: {
    total_direct: number;
    total_indirect: number;
    breaking_count: number;
    overall_risk: string;
    /** Pre-computed donut buckets. The UI reads these directly instead
     *  of iterating `changes` (catastrophic at Transcend scale). */
    by_severity?: BucketCount[];
    by_change_type?: BucketCount[];
    by_schema?: BucketCount[];
    by_breaking?: BucketCount[];
    /** Sum of usage query counts across the full diff. Drives the
     *  "Queries affected" KPI without the page having to reduce
     *  `changes` client-side. */
    total_query_count?: number;
  };
  /** Pagination metadata. */
  limit?: number;
  offset?: number;
  has_more?: boolean;
}

export interface TraverseNode {
  column_key: string;
  table_key: string;
  column_name: string;
  depth: number;
  path: string[];
  transformation_type: string | null;
  tier: string | null;
}

export interface ColumnTraverseResponse {
  column_key: string;
  snapshot_id: number;
  direction: string;
  nodes: TraverseNode[];
  total_hops: number;
}

// §2.12 AI Column Classification
export interface PiiEntry {
  column_id: number;
  column_name: string;
  data_type: string;
  pii_label: string | null;
  pii_confidence: number | null;
  pii_classified_at: string | null;
}

export interface PiiResponse {
  object: string;
  snapshot_id: number;
  columns: PiiEntry[];
}

export interface ClassifyColumnsResponse {
  snapshot_id: number;
  classified: number;
  skipped: number;
  errors: number;
}

export interface ReasoningResponse {
  change_id: number;
  classification: string;
  risk_level: string;
  recommendations: string[];
  explanation: string;
}

export interface BatchReasoningResponse {
  snapshot_from: number;
  snapshot_to: number;
  classification: string;
  risk_level: string;
  recommendations: string[];
  explanation: string;
  changes_analyzed: number;
}

export interface AskResponse {
  answer: string;
}

export interface SnapshotMetricsResponse {
  snapshot_id: number;
  schema_count: number;
  table_count: number;
  view_count: number;
  column_count: number;
  total_objects: number;
  structural_hash: string | null;
}

export interface GrowthResponse {
  snapshot_from: number;
  snapshot_to: number;
  objects_added: number;
  objects_removed: number;
  net_change: number;
  growth_percentage: number;
  schemas_added: number;
  schemas_removed: number;
  tables_added: number;
  tables_removed: number;
}

export interface VolatilityResponse {
  volatility_index: number;
  snapshot_count: number;
}

export interface UsageSummaryItem {
  object_name: string;
  object_type: string | null;
  schema_name: string | null;
  query_count: number;
  user_count: number;
}

export interface CriticalityItem {
  object_name: string;
  usage_score: number;
  graph_score: number;
  combined_score: number;
  criticality_level: string;
}

export interface CriticalityResponse {
  snapshot_id: number;
  items: CriticalityItem[];
  total: number;
  high_count: number;
  medium_count: number;
  low_count: number;
}

export interface EngineControlResponse {
  engine: string;
  action: string;
  status: string;
}

// DDL Generator
export interface DDLItem {
  change_id: number;
  object_identifier: string;
  change_type: string;
  severity: string | null;
  is_breaking: boolean | null;
  ddl_statements: string[];
  ddl_combined: string;
  taisa_warnings: string[];
}

export interface DDLResponse {
  snapshot_from: number;
  snapshot_to: number;
  total: number;
  items: DDLItem[];
}

// Timeline / History
export interface TimelineEvent {
  change_id: number;
  snapshot_from: number;
  snapshot_to: number;
  snapshot_id: number;
  snapshot_time: string;
  change_type: string;
  severity: string;
  is_breaking: boolean;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
}

export interface TimelineResponse {
  object_identifier: string;
  events: TimelineEvent[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface TimelineParams {
  limit?: number;
  offset?: number;
}

// Object Autocomplete (shared, replaces /timeline/objects for new UI code)
export interface ObjectSearchResponse {
  items: string[];
  has_more: boolean;
  source: "changes" | "graph";
}

export interface ObjectSearchParams {
  q?: string;
  snapshot_id?: number;
  source?: "changes" | "graph";
  /** Comma-separated whitelist of GraphNode.object_type values (only
   *  applies when source=graph). E.g. "TABLE,VIEW" for the Simulation
   *  page picker. */
  object_types?: string;
  limit?: number;
}

// Global Search
export interface SearchResult {
  object_name: string;
  object_type: string;
  schema_name: string;
  snapshot_id: number;
  context: string;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  total: number;
}

// Notifications / Alerts
export interface AlertItem {
  id: number;
  alert_type: string;
  severity: string;
  message: string;
  object_identifier: string;
  timestamp: string;
  source: string;
}

export interface AlertsResponse {
  alerts: AlertItem[];
  total: number;
}

// Export
export interface ExportResponse {
  filename: string;
  content: string;
  content_type: string;
}

// Report
export interface ReportResponse {
  snapshot_from: number;
  snapshot_to: number;
  generated_at: string;
  html: string;
}

// ──── Data-science pack (v1.07) ────
// Three analytical endpoints layered on top of change_event. Types here
// mirror the backend dataclasses 1:1.

export interface AnomalyRecord {
  schema_name: string;
  snapshot_id: number;
  observed: number;
  expected: number;
  std_dev: number;
  z_score: number;
  baseline_size: number;
  severity: "LOW" | "MEDIUM" | "HIGH";
}

export interface AnomaliesResponse {
  z_threshold: number;
  min_baseline: number;
  total: number;
  anomalies: AnomalyRecord[];
}

export interface CoChangePair {
  object_a: string;
  object_b: string;
  co_occurrences: number;
  occurrences_a: number;
  occurrences_b: number;
  total_deltas: number;
  support: number;
  confidence: number;
  lift: number;
}

export interface CoChangeResponse {
  total: number;
  min_lift: number;
  min_pair_support: number;
  pairs: CoChangePair[];
}

export interface VolatilityPoint {
  snapshot_id: number;
  volatility: number;
  objects_changed: number;
  objects_total: number;
}

export interface SchemaVolatilityTrend {
  schema_name: string;
  window: number;
  series: VolatilityPoint[];
  current_volatility: number;
  prior_volatility: number;
  delta: number;
  delta_pct: number;
  trend: "worsening" | "improving" | "stable";
}

export interface VolatilityTrendResponse {
  window: number;
  total: number;
  trends: SchemaVolatilityTrend[];
}

// Parser Import (DataDNA feed)
// Mirrors the `ImportResponse` pydantic model in backend/app/api/v1/parser_import.py.
// Counts dicts are open-ended: parser/ingestor may add new keys without a
// backend version bump, so we type them as loose Record<string, number>.
export interface ParserImportResponse {
  dry_run: boolean;
  snapshot_id: number | null;
  parse_run_id: string;
  parse_timestamp: string;
  input_counts: Record<string, number>;
  filtered_counts: Record<string, number>;
  persisted_counts: Record<string, number>;
  warnings: string[];
}

// Simulation ("what-if" analysis)
export interface SimulationImpact {
  object_name: string;
  impact_level: string;
  depth: number;
}

export interface SimulationRequest {
  object_identifier: string;
  change_type: string;
  snapshot_id: number;
  new_value?: string;
}

// §2.10 Reference Data
export interface ReferenceStatus {
  departments: number;
  teams: number;
  users: number;
  applications: number;
  schema_mappings: number;
  table_mappings: number;
}

export interface UserImportResponse {
  departments_upserted: number;
  teams_upserted: number;
  users_upserted: number;
  warnings: string[];
}

export interface AppImportResponse {
  applications_upserted: number;
  schema_mappings_upserted: number;
  table_mappings_upserted: number;
  warnings: string[];
}

export interface TeamRow {
  team_id: number;
  team_name: string;
  department_name: string | null;
  user_count: number;
}

export interface TeamsResponse {
  teams: TeamRow[];
  total: number;
}

export interface AppRow {
  application_id: number;
  application_name: string;
  description: string | null;
  owner_team: string | null;
  schema_count: number;
  table_count: number;
}

export interface ApplicationsResponse {
  applications: AppRow[];
  total: number;
}

export interface TeamUsageRow {
  team_name: string;
  department_name: string | null;
  query_count: number;
  user_count: number;
  object_count: number;
}

export interface TeamUsageResponse {
  snapshot_id: number | null;
  teams: TeamUsageRow[];
  unmapped_query_count: number;
  note: string | null;
}

export interface AppUsageRow {
  application_name: string;
  schema_count: number;
  table_count: number;
  query_count: number;
  user_count: number;
}

export interface AppUsageResponse {
  snapshot_id: number | null;
  applications: AppUsageRow[];
  unmapped_query_count: number;
}

export interface SimulationResponse {
  object_identifier: string;
  change_type: string;
  snapshot_id: number;
  is_breaking: boolean;
  severity: string;
  direct_impacts: SimulationImpact[];
  indirect_impacts: SimulationImpact[];
  queries_affected: number;
  users_affected: number;
  recommendation: string;
  risk_level: string;
}
