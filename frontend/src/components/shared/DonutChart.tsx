"use client";

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { CHART_COLORS } from "@/lib/constants";

interface DonutChartProps {
  title: string;
  data: { name: string; value: number; detail?: string }[];
  colors?: string[];
  showCenter?: boolean;
}

// Custom tooltip replaces Recharts' default so we can show the computed
// percentage share in addition to the raw count. Recharts injects
// `active` and `payload` automatically; `total` is passed from our parent.
function CustomTooltip({ active, payload, total }: any) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  const pct = total > 0 ? ((d.value / total) * 100).toFixed(1) : "0";
  return (
    <div className="bg-white border border-gray-200 shadow-lg rounded-lg p-3 text-xs">
      <div className="font-semibold text-td-navy mb-1">{d.name}</div>
      <div className="text-td-gray-dark">
        Count: <span className="font-bold text-td-navy">{d.value}</span>
      </div>
      <div className="text-td-gray-dark">
        Share: <span className="font-bold text-td-navy">{pct}%</span>
      </div>
      {d.detail && (
        <div className="text-td-gray-dark mt-1 border-t border-gray-100 pt-1">
          {d.detail}
        </div>
      )}
    </div>
  );
}

export default function DonutChart({
  title,
  data,
  colors = CHART_COLORS,
  showCenter = true,
}: DonutChartProps) {
  // Precompute the total once — used for both the tooltip's percentage
  // calculation and the center label.
  const total = data.reduce((sum, d) => sum + d.value, 0);

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
            >
              {data.map((_, i) => (
                <Cell key={i} fill={colors[i % colors.length]} />
              ))}
            </Pie>
            <Tooltip content={<CustomTooltip total={total} />} />
          </PieChart>
        </ResponsiveContainer>
        {/* Center text */}
        {showCenter && (
          <div
            className="absolute inset-0 flex items-center justify-center pointer-events-none"
          >
            <div className="text-center">
              <div className="text-2xl font-bold text-td-navy">{total}</div>
              <div className="text-[9px] text-td-gray-dark uppercase tracking-wider">Total</div>
            </div>
          </div>
        )}
      </div>
      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
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
