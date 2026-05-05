"use client";

import { useState } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer } from "recharts";
import { CHART_COLORS } from "@/lib/constants";

interface DonutChartProps {
  title: string;
  data: { name: string; value: number; detail?: string }[];
  colors?: string[];
  showCenter?: boolean;
}

export default function DonutChart({
  title,
  data,
  colors = CHART_COLORS,
  showCenter = true,
}: DonutChartProps) {
  // Precompute the total once — used both for the center label and for
  // the hover-state share percentage.
  const total = data.reduce((sum, d) => sum + d.value, 0);

  // Index of the slice the cursor is currently over, or null when no
  // slice is active. We render hover info in the donut's center hole
  // (replacing the "Total" label) instead of using a floating tooltip
  // that follows the cursor — the cursor sits inside the hole during
  // hover, which made the floating tooltip overlap the static center
  // label and produce unreadable stacked text.
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  if (data.length === 0 || total === 0) {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
        <h3 className="text-sm font-medium text-td-navy mb-3">{title}</h3>
        <div className="h-52 flex items-center justify-center text-xs text-td-gray-dark">
          No data to display
        </div>
      </div>
    );
  }

  const activeSlice = activeIndex != null ? data[activeIndex] : null;
  const activePct =
    activeSlice && total > 0
      ? ((activeSlice.value / total) * 100).toFixed(1)
      : null;

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
      <h3 className="text-sm font-medium text-td-navy mb-3">{title}</h3>
      <div style={{ width: "100%", height: 208, position: "relative" }}>
        <ResponsiveContainer width="100%" height={208}>
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={50}
              outerRadius={80}
              dataKey="value"
              stroke="#fff"
              strokeWidth={2}
              onMouseEnter={(_, idx) => setActiveIndex(idx)}
              onMouseLeave={() => setActiveIndex(null)}
            >
              {data.map((_, i) => (
                <Cell
                  key={i}
                  fill={colors[i % colors.length]}
                  opacity={activeIndex == null || activeIndex === i ? 1 : 0.45}
                />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        {/* Center text — swaps between "Total" and the hovered slice's
            details. Single positioned element, so nothing can overlap. */}
        {showCenter && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            {activeSlice ? (
              <div className="text-center px-2">
                <div
                  className="text-[10px] font-semibold uppercase tracking-wider truncate max-w-[100px]"
                  style={{ color: colors[(activeIndex ?? 0) % colors.length] }}
                  title={activeSlice.name}
                >
                  {activeSlice.name}
                </div>
                <div className="text-2xl font-bold text-td-navy leading-tight">
                  {activeSlice.value}
                </div>
                <div className="text-[10px] text-td-gray-dark font-mono">
                  {activePct}%
                </div>
              </div>
            ) : (
              <div className="text-center">
                <div className="text-2xl font-bold text-td-navy">{total}</div>
                <div className="text-[9px] text-td-gray-dark uppercase tracking-wider">
                  Total
                </div>
              </div>
            )}
          </div>
        )}
      </div>
      {/* Detail strip — shown below the donut when the active slice
          has a `detail` field. Lives outside the chart so long strings
          ("Affected: tableA, tableB, tableC...") wrap cleanly instead
          of getting truncated to fit the 100 px donut hole. Reserves
          a fixed-height row even when empty so the legend below
          doesn't jump as the user moves the cursor across slices. */}
      <div className="min-h-[1.25rem] mt-1 text-[11px] text-td-gray-dark leading-snug">
        {activeSlice?.detail ?? ""}
      </div>
      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1">
        {data.map((d, i) => (
          <div key={d.name} className="flex items-center gap-1.5 text-xs text-td-gray-dark">
            <span
              className="w-2.5 h-2.5 rounded-full shrink-0"
              style={{ backgroundColor: colors[i % colors.length] }}
            />
            {d.name} ({d.value})
          </div>
        ))}
      </div>
    </div>
  );
}
