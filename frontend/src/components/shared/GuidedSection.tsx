"use client";

/**
 * GuidedSection — narrative section wrapper used across report-style pages.
 *
 * Purpose: when a page has many charts/tables the user doesn't know what to
 * look at first. Wrapping each block in a `<GuidedSection>` gives them:
 *  - a numbered title ("1. Risk classification")
 *  - a short subtitle fragment ("Each change scored along 2 dimensions")
 *  - a plain-English intro paragraph explaining what they're about to see
 *    and how to read it.
 *
 * First introduced on the Impact page redesign (v1.08.01) and then rolled
 * out to Intelligence / Metrics / Usage (v1.09.00). Kept as a shared
 * component so the visual language stays consistent — same icon slot, same
 * blue-tinted intro box, same spacing rhythm across pages.
 */

import { Info } from "lucide-react";
import type { ComponentType, ReactNode } from "react";

type SectionIcon = ComponentType<{ size?: number; className?: string }>;

export function GuidedSection({
  title,
  subtitle,
  icon: Icon,
  intro,
  children,
}: {
  title: string;
  subtitle?: string;
  icon: SectionIcon;
  intro: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="mb-6">
      <div className="flex items-center gap-2 mb-1 flex-wrap">
        <Icon size={16} className="text-td-navy" />
        <h3 className="text-sm font-bold text-td-navy">{title}</h3>
        {subtitle && <span className="text-[11px] text-td-gray-dark">· {subtitle}</span>}
      </div>
      <div className="bg-blue-50/40 border border-blue-100 rounded-lg px-3 py-2 mb-3 flex items-start gap-2">
        <Info size={12} className="text-blue-500 shrink-0 mt-0.5" />
        <p className="text-[11px] text-td-gray-dark leading-relaxed">{intro}</p>
      </div>
      {children}
    </section>
  );
}

/**
 * HeroStat — compact labelled number used inside the hero strip of a
 * report page. Formats >= 1000 as "1.2K" so the row doesn't break.
 */
export function HeroStat({
  value,
  label,
  tooltip,
  color,
}: {
  value: number | string;
  label: string;
  tooltip?: string;
  color: string;
}) {
  const display =
    typeof value === "number"
      ? value >= 1000
        ? `${(value / 1000).toFixed(1)}K`
        : value.toLocaleString()
      : value;
  return (
    <div className="text-center">
      <div className="text-2xl font-bold" style={{ color }}>
        {display}
      </div>
      <div className="text-[10px] text-td-gray-dark inline-flex items-center gap-1 justify-center">
        {label}
        {tooltip && (
          <span title={tooltip} className="cursor-help text-td-gray-dark/60">
            ⓘ
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * BigStat — 3-up card-style stat used to emphasise a handful of key
 * numbers inside a section (e.g. Impact spread: 3 stats).
 */
export function BigStat({
  value,
  label,
  hint,
  color,
}: {
  value: number | string;
  label: string;
  hint?: string;
  color: string;
}) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <div className="text-3xl font-bold mb-1" style={{ color }}>
        {value}
      </div>
      <div className="text-xs font-semibold text-td-navy">{label}</div>
      {hint && <div className="text-[10px] text-td-gray-dark mt-0.5">{hint}</div>}
    </div>
  );
}
