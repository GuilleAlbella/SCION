"use client";

import AnimatedCounter from "./AnimatedCounter";

interface KpiCardProps {
  label: string;
  value: string | number;
  color?: string;
}

/**
 * KpiCard — small metric tile used across dashboards. Numeric values get
 * the animated tween; string values render statically (e.g. "N/A", "OK").
 */
export default function KpiCard({ label, value, color }: KpiCardProps) {
  // Only animate real numbers. Strings like "N/A" wouldn't make sense tweening.
  const isNumber = typeof value === "number";

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 px-5 py-4 flex flex-col">
      <span className="text-xs text-td-gray-dark uppercase tracking-wider">
        {label}
      </span>
      {isNumber ? (
        <AnimatedCounter
          value={value}
          className="text-3xl font-bold mt-1"
          style={color ? { color } : undefined}
        />
      ) : (
        <span
          className="text-3xl font-bold mt-1"
          style={color ? { color } : undefined}
        >
          {value}
        </span>
      )}
    </div>
  );
}
