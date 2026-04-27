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
}

export interface SnapshotsResponse {
  snapshots: Snapshot[];
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
  changes: DiffDetailItem[];
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

export interface BatchBlastRadius {
  total_impacted_nodes: number;
  max_depth: number;
  weighted_score: number;
  affected_schemas: string[];
  affected_tables: string[];
}

export interface BatchImpactResponse {
  snapshot_from: number;
  snapshot_to: number;
  changes_analyzed: number;
  blast_radius: BatchBlastRadius;
  changes: BatchChangeImpact[];
  summary: {
    total_direct: number;
    total_indirect: number;
    breaking_count: number;
    overall_risk: string;
  };
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
  structural_hash: string;
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
