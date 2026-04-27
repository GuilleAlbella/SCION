"use client";

// Header — slim title bar rendered by PageShell at the top of every page.
// Kept intentionally minimal; page-specific toolbars live in the page body.

interface HeaderProps {
  title: string;
  subtitle?: string;
}

export default function Header({ title, subtitle }: HeaderProps) {
  return (
    <div className="bg-td-navy px-6 py-4">
      <h1 className="text-white text-lg font-semibold">{title}</h1>
      {subtitle && (
        <p className="text-white/60 text-sm mt-0.5">{subtitle}</p>
      )}
    </div>
  );
}
