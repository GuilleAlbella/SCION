"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSelection } from "@/lib/SelectionContext";
import GlobalSearch from "@/components/shared/GlobalSearch";
import { useTheme } from "@/lib/ThemeContext";
import VersionPill from "@/components/layout/VersionPill";
import NotificationBell from "@/components/layout/NotificationBell";
import { Moon, Sun } from "lucide-react";
import {
  LayoutDashboard,
  Camera,
  GitCompareArrows,
  Target,
  Network,
  Settings,
  TrendingUp,
  BarChart3,
  Flame,
  ShieldCheck,
  Clock,
  Bell,
  FlaskConical,
  Building2,
  LayoutGrid,
} from "lucide-react";

// Top-level navigation. Order reflects the intended user flow:
// observe (Dashboard, Landscape, Snapshots) → analyse (Changes, Impact, What-If) →
// explore (Lineage, Graph) → measure (Metrics, Usage, Intelligence) →
// access (Landscape) → operate (Timeline, Alerts, Control).
const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/landscape", label: "Landscape", icon: LayoutGrid },
  { href: "/snapshots", label: "Snapshots", icon: Camera },
  { href: "/changes", label: "Changes", icon: GitCompareArrows },
  { href: "/impact", label: "Impact Analysis", icon: Target },
  { href: "/simulation", label: "What-If", icon: FlaskConical },
  { href: "/lineage", label: "Lineage", icon: TrendingUp },
  { href: "/graph", label: "Graph", icon: Network },
  { href: "/metrics", label: "Metrics", icon: BarChart3 },
  { href: "/usage", label: "Usage", icon: Flame },
  { href: "/intelligence", label: "Intelligence", icon: ShieldCheck },
  // §2.10 Reference Data (Phase 2): org hierarchy + business application metadata
  { href: "/reference", label: "Reference", icon: Building2 },
  { href: "/timeline", label: "Timeline", icon: Clock },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/control", label: "Control", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { activeDiffPair } = useSelection();
  const { dark, toggle } = useTheme();

  return (
    <aside className="w-60 min-h-screen bg-td-navy text-white flex flex-col">
      {/* Branding */}
      <div className="px-4 py-5 border-b border-white/10">
        <div className="flex items-center justify-between">
          <div className="text-td-orange font-bold text-sm tracking-wide">teradata.</div>
          <div className="flex items-center gap-1.5">
            <NotificationBell />
            <button
              onClick={toggle}
              className="w-7 h-7 rounded-lg bg-white/10 hover:bg-white/20 flex items-center justify-center transition-colors"
              title={dark ? "Switch to Light Mode" : "Switch to Dark Mode"}
            >
              {dark ? <Sun size={13} className="text-yellow-400" /> : <Moon size={13} className="text-white/60" />}
            </button>
          </div>
        </div>
        <div className="mt-1">
          <span className="text-white text-lg font-light tracking-[0.15em]">PROJECT</span>
          <span className="text-td-orange text-lg font-bold tracking-[0.08em] ml-1.5">SCION</span>
        </div>
        <p className="text-[9px] text-white/40 mt-1.5 tracking-[0.2em] uppercase leading-snug">
          Structural Change Intelligence
          <br />
          & Observability Node
        </p>
      </div>

      {/* Active context indicator */}
      {activeDiffPair && (
        <div className="px-4 py-2 border-b border-white/10 bg-white/5">
          <div className="text-[10px] text-white/40 uppercase tracking-wider">Active Diff</div>
          <div className="text-xs text-td-orange font-medium">
            #{activeDiffPair.snapshotFrom} → #{activeDiffPair.snapshotTo}
          </div>
        </div>
      )}

      {/* Global Search */}
      <div className="px-3 py-2 border-b border-white/10">
        <GlobalSearch />
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          // Dashboard requires an exact match so that e.g. /impact doesn't
          // also light up "Dashboard"; all other items use prefix-match so
          // nested routes keep their parent highlighted.
          const active =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                active
                  ? "bg-white/10 text-white font-medium border-l-2 border-td-orange"
                  : "text-white/70 hover:bg-white/5 hover:text-white border-l-2 border-transparent"
              }`}
            >
              <Icon size={18} />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-white/10">
        <VersionPill />
      </div>
    </aside>
  );
}
