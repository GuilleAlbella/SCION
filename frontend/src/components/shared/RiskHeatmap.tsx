"use client";

import { useState } from "react";

interface HeatmapItem {
  name: string;
  score: number;
  level: string;
  detail?: string;
}

interface Props {
  items: HeatmapItem[];
  title?: string;
  // Optional one-liner shown under the title clarifying what one cell
  // represents (e.g. "one cell = one object" vs. a time bucket). Added
  // because users assumed this was a time-series heatmap by default.
  description?: string;
}

const LEVEL_COLORS: Record<string, string> = {
  HIGH: "#DC2626",
  MEDIUM: "#F59E0B",
  LOW: "#16A34A",
};

/**
 * RiskHeatmap — grid of coloured tiles where hue encodes risk level and
 * opacity encodes criticality score. Used on the Intelligence page to show
 * the riskiest objects at a glance.
 */
export default function RiskHeatmap({ items, title = "Risk Heatmap", description }: Props) {
  // Track the hovered tile to show full details below the grid —
  // deliberately single-item (no persistent selection) to keep the UI calm.
  const [hovered, setHovered] = useState<HeatmapItem | null>(null);

  if (items.length === 0) return null;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
      <h3 className="text-sm font-semibold text-td-navy mb-1">{title}</h3>
      {description && (
        <p className="text-[11px] text-td-gray-dark mb-3">{description}</p>
      )}
      {!description && <div className="mb-4" />}

      {/* Heatmap grid — fewer, larger cells so labels are readable */}
      <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${Math.min(Math.ceil(Math.sqrt(items.length)), 6)}, 1fr)` }}>
        {items.map((item) => {
          const color = LEVEL_COLORS[item.level] ?? "#7C8185";
          // Floor opacity at 0.4 so low-score tiles remain legible — pure
          // score would fade near-zero tiles to invisibility.
          const intensity = Math.max(0.4, Math.min(item.score, 1));
          // Strip schema/db prefix so tile labels stay readable in small cells.
          const shortName = item.name.split(".").pop() ?? item.name;
          return (
            <div
              key={item.name}
              className="relative rounded-lg flex flex-col items-center justify-center cursor-default transition-transform hover:scale-105 hover:z-10 p-3 shadow-sm"
              style={{
                backgroundColor: color,
                opacity: intensity,
                minHeight: 80,
              }}
              onMouseEnter={() => setHovered(item)}
              onMouseLeave={() => setHovered(null)}
              title={`${item.name} — ${item.level} (${(item.score * 100).toFixed(0)}%)`}
            >
              <span className="text-white text-xs font-semibold text-center leading-tight break-all">
                {shortName}
              </span>
              <span className="text-white/90 text-[10px] font-mono mt-1">
                {(item.score * 100).toFixed(0)}%
              </span>
            </div>
          );
        })}
      </div>

      {/* Hover detail */}
      {hovered && (
        <div className="mt-4 pt-3 border-t border-gray-100 flex items-center gap-3 flex-wrap">
          <span
            className="w-4 h-4 rounded"
            style={{ backgroundColor: LEVEL_COLORS[hovered.level] ?? "#7C8185" }}
          />
          <span className="text-sm font-mono text-td-navy font-medium">{hovered.name}</span>
          <span
            className="text-xs font-bold px-2 py-0.5 rounded-full text-white"
            style={{ backgroundColor: LEVEL_COLORS[hovered.level] ?? "#7C8185" }}
          >
            {hovered.level}
          </span>
          <span className="text-sm text-td-gray-dark">{(hovered.score * 100).toFixed(0)}% criticality</span>
          {hovered.detail && <span className="text-xs text-td-gray-dark ml-auto">{hovered.detail}</span>}
        </div>
      )}

      {/* Legend */}
      <div className="mt-4 pt-3 border-t border-gray-100 flex items-center gap-5 text-xs text-td-gray-dark flex-wrap">
        <span className="flex items-center gap-1.5"><span className="w-4 h-4 rounded bg-red-600" /> HIGH</span>
        <span className="flex items-center gap-1.5"><span className="w-4 h-4 rounded bg-amber-500" /> MEDIUM</span>
        <span className="flex items-center gap-1.5"><span className="w-4 h-4 rounded bg-green-600" /> LOW</span>
        <span className="ml-auto text-[11px]">Opacity = criticality score (darker = more critical)</span>
      </div>
    </div>
  );
}
