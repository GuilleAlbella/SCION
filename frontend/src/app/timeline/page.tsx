"use client";

import { useState, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import PageShell from "@/components/layout/PageShell";
import LoadingSpinner from "@/components/shared/LoadingSpinner";
import ErrorAlert from "@/components/shared/ErrorAlert";
import EmptyState from "@/components/shared/EmptyState";
import { getTimeline, getTimelineObjects } from "@/lib/api/timeline";
import type { TimelineResponse, TimelineEvent } from "@/lib/api/types";
import { Clock, Search, ChevronRight, ShieldAlert } from "lucide-react";
import { changeTypeLabel } from "@/lib/terminology";

const SEVERITY_COLORS: Record<string, string> = {
  HIGH: "#DC2626",
  MEDIUM: "#F59E0B",
  LOW: "#16A34A",
};

export default function TimelinePageWrapper() {
  return (
    <Suspense fallback={<PageShell title="Timeline / History"><LoadingSpinner /></PageShell>}>
      <TimelinePage />
    </Suspense>
  );
}

function TimelinePage() {
  const [objects, setObjects] = useState<string[]>([]);
  const [selected, setSelected] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);

  const searchParams = useSearchParams();

  useEffect(() => {
    getTimelineObjects()
      .then((data) => setObjects(data.objects))
      .catch(() => {});
  }, []);

  // Entry from Changes page quick-link (?object=db.tbl). Deps omit
  // handleLoad intentionally — it would cause re-fetches on every render
  // since it's redefined each time.
  useEffect(() => {
    const obj = searchParams.get("object");
    if (obj) handleLoad(obj);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  async function handleLoad(objectName: string) {
    setSelected(objectName);
    setLoading(true);
    setError(null);
    try {
      const data = await getTimeline(objectName);
      setTimeline(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load timeline");
    } finally {
      setLoading(false);
    }
  }

  const filteredObjects = searchTerm
    ? objects.filter((o) => o.toLowerCase().includes(searchTerm.toLowerCase()))
    : objects;

  return (
    <PageShell title="Timeline / History" subtitle="Object evolution across snapshots">
      {/* Object selector */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        <div className="flex items-center gap-3 mb-3">
          <Clock size={18} className="text-td-navy" />
          <h3 className="text-sm font-semibold text-td-navy">Select an Object</h3>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-td-gray-dark" />
            <input
              type="text"
              placeholder="Search objects..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full border border-gray-300 rounded pl-9 pr-3 py-1.5 text-sm"
            />
          </div>
          <select
            value={selected}
            onChange={(e) => {
              if (e.target.value) handleLoad(e.target.value);
            }}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm max-w-sm"
          >
            <option value="">Select object...</option>
            {filteredObjects.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        </div>
      </div>

      {error && <ErrorAlert message={error} />}
      {loading && <LoadingSpinner />}

      {/* Timeline visualization */}
      {timeline && timeline.events.length > 0 && (
        <div className="relative">
          <div className="flex items-center gap-2 mb-4">
            <Clock size={16} className="text-td-navy" />
            <h2 className="text-sm font-bold text-td-navy">
              {timeline.object_identifier} — {timeline.total} change(s)
            </h2>
          </div>

          {/* Timeline */}
          <div className="relative pl-8">
            {/* Vertical line */}
            <div className="absolute left-3 top-0 bottom-0 w-0.5 bg-td-navy/20" />

            {timeline.events.map((event, idx) => (
              <TimelineCard key={event.change_id} event={event} isLast={idx === timeline.events.length - 1} />
            ))}
          </div>
        </div>
      )}

      {timeline && timeline.events.length === 0 && (
        <EmptyState message={`No changes found for "${timeline.object_identifier}".`} />
      )}

      {!timeline && !loading && (
        <EmptyState message="Select an object to see its change history over time." />
      )}
    </PageShell>
  );
}

// Each card is a vertical-timeline entry with a colored dot that aligns with
// the shared vertical line drawn by the parent. Local `expanded` state keeps
// each card independent — expanding one doesn't collapse others.
function TimelineCard({ event, isLast }: { event: TimelineEvent; isLast: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const sevColor = SEVERITY_COLORS[event.severity] ?? "#7C8185";

  return (
    <div className={`relative mb-6 ${isLast ? "" : ""}`}>
      {/* Dot on timeline */}
      <div
        className="absolute -left-5 top-3 w-3 h-3 rounded-full border-2 border-white"
        style={{ backgroundColor: sevColor }}
      />

      <div
        className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 cursor-pointer hover:shadow-md transition-shadow"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs text-td-gray-dark font-mono">
                Snapshot #{event.snapshot_from} → #{event.snapshot_to}
              </span>
              {event.snapshot_time && (
                <span className="text-xs text-td-gray-dark">
                  {new Date(event.snapshot_time).toLocaleDateString()}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span
                className="bg-td-orange/10 text-td-orange px-2 py-0.5 rounded text-xs font-medium"
                title={event.change_type}
              >
                {changeTypeLabel(event.change_type)}
              </span>
              <span
                className="px-2 py-0.5 rounded-full text-xs font-medium"
                style={{ backgroundColor: `${sevColor}20`, color: sevColor }}
              >
                {event.severity}
              </span>
              {event.is_breaking && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-600 text-white">
                  <ShieldAlert size={10} />
                  BREAKING
                </span>
              )}
            </div>
          </div>
          <ChevronRight
            size={16}
            className={`text-td-gray-dark transition-transform ${expanded ? "rotate-90" : ""}`}
          />
        </div>

        {expanded && (
          <div className="mt-3 pt-3 border-t border-gray-100 grid grid-cols-2 gap-4 text-xs">
            <div>
              <span className="font-semibold text-red-600 block mb-1">Before</span>
              <pre className="bg-gray-50 rounded p-2 overflow-auto max-h-32 border border-gray-200">
                {event.before_state ? JSON.stringify(event.before_state, null, 2) : "null"}
              </pre>
            </div>
            <div>
              <span className="font-semibold text-green-600 block mb-1">After</span>
              <pre className="bg-gray-50 rounded p-2 overflow-auto max-h-32 border border-gray-200">
                {event.after_state ? JSON.stringify(event.after_state, null, 2) : "null"}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
