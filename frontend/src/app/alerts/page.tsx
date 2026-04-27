"use client";

import { useState, useEffect } from "react";
import PageShell from "@/components/layout/PageShell";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { getAlerts, getAnomalies } from "@/lib/api/alerts";
import type { AlertsResponse, AnomaliesResponse } from "@/lib/api/types";
import { Bell, ShieldAlert, AlertTriangle, Brain, RefreshCw, Unlink, AlertCircle, Network, Activity, TrendingUp, TrendingDown } from "lucide-react";

// Six alert types the backend can emit. The record keys MUST match the
// `alert_type` strings returned by /alerts — any unknown type falls back
// to HIGH_SEVERITY styling (see lookup in the render loop).
const ALERT_TYPE_CONFIG: Record<string, { icon: typeof ShieldAlert; color: string; label: string }> = {
  BREAKING_CHANGE:     { icon: ShieldAlert,   color: "#DC2626", label: "Breaking Change" },
  HIGH_SEVERITY:       { icon: AlertTriangle, color: "#F59E0B", label: "High Severity" },
  HIGH_RISK_REASONING: { icon: Brain,         color: "#7C2D12", label: "High Risk (TAISA)" },
  BROKEN_LINEAGE:      { icon: Unlink,        color: "#B91C1C", label: "Broken Lineage" },
  ORPHAN_OBJECT:       { icon: AlertCircle,   color: "#D97706", label: "Orphan Object" },
  HUB_CHANGED:         { icon: Network,       color: "#7C3AED", label: "Hub Changed" },
};

export default function AlertsPage() {
  const [data, setData] = useState<AlertsResponse | null>(null);
  const [anomalies, setAnomalies] = useState<AnomaliesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("ALL");

  async function loadAlerts() {
    setLoading(true);
    setError(null);
    try {
      // Two independent fetches; a failure in one shouldn't blank the other.
      const [alertsRes, anomaliesRes] = await Promise.allSettled([
        getAlerts(100),
        getAnomalies(2.0),
      ]);
      if (alertsRes.status === "fulfilled") setData(alertsRes.value);
      if (anomaliesRes.status === "fulfilled") setAnomalies(anomaliesRes.value);
      if (alertsRes.status === "rejected") {
        setError(alertsRes.reason?.message ?? "Failed to load alerts");
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load alerts");
    } finally {
      setLoading(false);
    }
  }

  // Load on mount; the Refresh button re-runs the same fetch.
  useEffect(() => { loadAlerts(); }, []);

  const alerts = data?.alerts ?? [];
  const filtered = filter === "ALL" ? alerts : alerts.filter((a) => a.alert_type === filter);

  const breakingCount = alerts.filter((a) => a.alert_type === "BREAKING_CHANGE").length;
  const highSevCount = alerts.filter((a) => a.alert_type === "HIGH_SEVERITY").length;
  const reasoningCount = alerts.filter((a) => a.alert_type === "HIGH_RISK_REASONING").length;

  return (
    <PageShell title="Notifications & Alerts" subtitle="Recent breaking changes, high-severity events, and risk warnings">
      {/* Stats bar */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
          <div className="text-2xl font-bold text-td-navy">{alerts.length}</div>
          <div className="text-[10px] text-td-gray-dark uppercase tracking-wider">Total Alerts</div>
        </div>
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
          <div className="text-2xl font-bold text-red-600">{breakingCount}</div>
          <div className="text-[10px] text-td-gray-dark uppercase tracking-wider">Breaking</div>
        </div>
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
          <div className="text-2xl font-bold text-amber-600">{highSevCount}</div>
          <div className="text-[10px] text-td-gray-dark uppercase tracking-wider">High Severity</div>
        </div>
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 text-center">
          <div className="text-2xl font-bold text-orange-900">{reasoningCount}</div>
          <div className="text-[10px] text-td-gray-dark uppercase tracking-wider">TAISA Risk</div>
        </div>
      </div>

      {/* ──── Statistical Anomalies ──── z-score driven; distinct from
          the rule-based alerts below because its shape (expected vs
          observed, baseline size) doesn't fit the generic AlertItem card. */}
      {anomalies && anomalies.anomalies.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border-2 border-purple-200 p-5 mb-6">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-purple-100 flex items-center justify-center">
              <Activity size={16} className="text-purple-700" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-td-navy">Statistical Anomalies</h3>
              <p className="text-[11px] text-td-gray-dark">
                Volume spikes flagged by z-score &ge; {anomalies.z_threshold}σ against each schema&apos;s own history.
                No fixed rules — pure statistical process control.
              </p>
            </div>
            <span className="ml-auto px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 text-purple-700">
              {anomalies.total}
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {anomalies.anomalies.slice(0, 8).map((a, i) => {
              const sevColor = a.severity === "HIGH" ? "#DC2626" : a.severity === "MEDIUM" ? "#F59E0B" : "#16A34A";
              const up = a.z_score > 0;
              const Icon = up ? TrendingUp : TrendingDown;
              return (
                <div key={i} className="border rounded-lg p-3 flex items-start gap-3" style={{ borderColor: `${sevColor}40` }}>
                  <Icon size={16} style={{ color: sevColor }} className="mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-xs font-semibold text-td-navy font-mono">{a.schema_name}</span>
                      <span className="text-[10px] text-td-gray-dark">snapshot #{a.snapshot_id}</span>
                      <span
                        className="ml-auto px-1.5 py-0.5 rounded text-[9px] font-bold text-white"
                        style={{ backgroundColor: sevColor }}
                      >
                        z = {a.z_score > 0 ? "+" : ""}{a.z_score}σ
                      </span>
                    </div>
                    <div className="text-[11px] text-td-gray-dark">
                      Observed <strong className="text-td-navy">{a.observed}</strong> change(s) —
                      expected <strong className="text-td-navy">~{a.expected}</strong> (±{a.std_dev})
                      based on {a.baseline_size} prior snapshot(s).
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          {anomalies.anomalies.length > 8 && (
            <div className="text-[10px] text-td-gray-dark mt-2">
              Showing top 8 of {anomalies.anomalies.length} anomalies.
            </div>
          )}
        </div>
      )}

      {/* Filter + refresh */}
      <div className="flex items-center gap-3 mb-4">
        <div className="flex items-center gap-2 text-xs">
          <Bell size={14} className="text-td-navy" />
          <span className="text-td-gray-dark">Filter:</span>
          {[
            { key: "ALL", label: "All" },
            { key: "BREAKING_CHANGE", label: "Breaking" },
            { key: "HIGH_SEVERITY", label: "High Severity" },
            { key: "HIGH_RISK_REASONING", label: "TAISA Risk" },
            { key: "BROKEN_LINEAGE", label: "Broken Lineage" },
            { key: "ORPHAN_OBJECT", label: "Orphans" },
            { key: "HUB_CHANGED", label: "Hub Changes" },
          ].map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`px-2 py-1 rounded text-xs font-medium transition-colors ${
                filter === f.key
                  ? "bg-td-navy text-white"
                  : "bg-gray-100 text-td-gray-dark hover:bg-gray-200"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <button
          onClick={loadAlerts}
          disabled={loading}
          className="ml-auto flex items-center gap-1 text-xs text-td-gray-dark hover:text-td-navy transition-colors"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {error && <ErrorAlert message={error} />}
      {loading && <LoadingSpinner />}

      {!loading && filtered.length === 0 && (
        <EmptyState message="No alerts to show. The system is clean." />
      )}

      {/* Alert cards */}
      <div className="space-y-3">
        {filtered.map((alert) => {
          const config = ALERT_TYPE_CONFIG[alert.alert_type] ?? ALERT_TYPE_CONFIG.HIGH_SEVERITY;
          const Icon = config.icon;
          return (
            <div
              key={alert.id}
              className="bg-white rounded-lg shadow-sm border-l-4 border-gray-200 p-4 hover:shadow-md transition-shadow"
              style={{ borderLeftColor: config.color }}
            >
              <div className="flex items-start gap-3">
                <Icon size={18} style={{ color: config.color }} className="mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className="px-2 py-0.5 rounded-full text-[10px] font-bold text-white"
                      style={{ backgroundColor: config.color }}
                    >
                      {config.label}
                    </span>
                    <span className="text-[10px] text-td-gray-dark">{alert.source}</span>
                  </div>
                  <p className="text-sm text-td-navy">{alert.message}</p>
                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-xs font-mono text-td-gray-dark">{alert.object_identifier}</span>
                    {alert.timestamp && (
                      <span className="text-[10px] text-td-gray-dark">
                        {new Date(alert.timestamp).toLocaleString()}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </PageShell>
  );
}
