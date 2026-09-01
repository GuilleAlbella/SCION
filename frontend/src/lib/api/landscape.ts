import client from "./client";

export interface RiskObject {
  object_name: string;
  schema_name: string;
  combined_score: number;
  criticality_level: "HIGH" | "MEDIUM" | "LOW";
  snapshot_id: number;
}

export interface LandscapeSummary {
  latest_snapshot_id: number | null;
  latest_snapshot_time: string | null;
  entity_count: number;
  active_entity_count: number;
  high_risk_count: number;
  recent_changes_count: number;
  top_risk_objects: RiskObject[];
}

export interface RiskDistribution {
  HIGH: number;
  MEDIUM: number;
  LOW: number;
}

export interface LandscapeRiskOverview {
  snapshot_id: number | null;
  risk_distribution: RiskDistribution;
  top_critical: RiskObject[];
  recently_changed_high_risk: RiskObject[];
}

export async function getLandscapeSummary(topN = 10): Promise<LandscapeSummary> {
  const { data } = await client.get("/landscape/summary", { params: { top_n: topN } });
  return data;
}

export async function getLandscapeRiskOverview(
  snapshotId?: number,
  topN = 10,
): Promise<LandscapeRiskOverview> {
  const { data } = await client.get("/landscape/risk-overview", {
    params: { snapshot_id: snapshotId, top_n: topN },
  });
  return data;
}

// §2.15 Progressive Disclosure — schema-level drill-down

export interface SchemaRiskSummary {
  schema_name: string;
  total_objects: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  avg_score: number;
}

export async function getLandscapeSchemas(snapshotId?: number): Promise<SchemaRiskSummary[]> {
  const { data } = await client.get("/landscape/schemas", {
    params: { snapshot_id: snapshotId },
  });
  return data;
}

export async function getSchemaObjects(schemaName: string, snapshotId?: number): Promise<RiskObject[]> {
  const { data } = await client.get(`/landscape/schemas/${encodeURIComponent(schemaName)}/objects`, {
    params: { snapshot_id: snapshotId },
  });
  return data;
}
