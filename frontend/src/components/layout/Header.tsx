"use client";

// Header — slim title bar rendered by PageShell at the top of every page.
// Kept intentionally minimal; page-specific toolbars live in the page body.

import type { LucideIcon } from "lucide-react";

interface HeaderProps {
  title: string;
  subtitle?: string;
  icon?: LucideIcon;
}

export default function Header({ title, subtitle, icon: Icon }: HeaderProps) {
  return (
    <div className="bg-td-navy px-6 py-4">
      <div className="flex items-center gap-2">
        {Icon && <Icon size={18} className="text-white/70" />}
        <h1 className="text-white text-lg font-semibold">{title}</h1>
      </div>
      {subtitle && (
        <p className="text-white/60 text-sm mt-0.5">{subtitle}</p>
      )}
    </div>
  );
}
