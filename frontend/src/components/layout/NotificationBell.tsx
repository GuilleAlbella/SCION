"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Bell, Database, GitBranch, Activity, FileText, X } from "lucide-react";
import {
  fetchNotifications,
  type DataAvailableNotification,
} from "@/lib/api/notifications";

const POLL_INTERVAL_MS = 60_000;

const CATEGORY_LABEL: Record<string, string> = {
  dict:    "Data Dictionary",
  lineage: "Data Lineage",
  pdcr:    "Object Usage",
  dbql:    "DBQL",
};

const CATEGORY_ICON: Record<string, React.ElementType> = {
  dict:    Database,
  lineage: GitBranch,
  pdcr:    Activity,
  dbql:    FileText,
};

export default function NotificationBell() {
  const router = useRouter();
  const [notifications, setNotifications] = useState<DataAvailableNotification[]>([]);
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  // Poll the backend
  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const data = await fetchNotifications();
        if (!cancelled) setNotifications(data.notifications);
      } catch {
        // share not reachable — stay quiet
      }
    }

    poll();
    const id = setInterval(poll, POLL_INTERVAL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Close panel on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const count = notifications.length;

  return (
    <div className="relative" ref={panelRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative w-7 h-7 rounded-lg bg-white/10 hover:bg-white/20 flex items-center justify-center transition-colors"
        title="Data notifications"
      >
        <Bell size={13} className={count > 0 ? "text-td-orange" : "text-white/60"} />
        {count > 0 && (
          <span className="absolute -top-1 -right-1 w-3.5 h-3.5 bg-td-orange rounded-full text-[8px] font-bold text-white flex items-center justify-center">
            {count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute left-0 top-9 z-50 w-72 bg-td-navy border border-white/20 rounded-xl shadow-2xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
            <span className="text-xs font-semibold text-white/80 uppercase tracking-wider">
              Notifications
            </span>
            <button onClick={() => setOpen(false)} className="text-white/40 hover:text-white/80">
              <X size={13} />
            </button>
          </div>

          {count === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-white/40">
              No new data available
            </div>
          ) : (
            <div className="divide-y divide-white/10">
              {notifications.map((n, i) => (
                <NotificationCard
                  key={i}
                  notification={n}
                  onImport={() => {
                    setOpen(false);
                    router.push("/snapshots?autoImport=true");
                  }}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function NotificationCard({
  notification,
  onImport,
}: {
  notification: DataAvailableNotification;
  onImport: () => void;
}) {
  return (
    <div className="px-4 py-3">
      <div className="flex items-start gap-2 mb-2">
        <Bell size={14} className="text-td-orange mt-0.5 shrink-0" />
        <div>
          <p className="text-xs font-medium text-white">
            New snapshot data available
          </p>
          <p className="text-[10px] text-white/50 mt-0.5">{notification.date}</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 mb-3">
        {notification.files.map((f) => {
          const Icon = CATEGORY_ICON[f] ?? FileText;
          return (
            <span
              key={f}
              className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-white/10 text-[10px] text-white/70"
            >
              <Icon size={9} />
              {CATEGORY_LABEL[f] ?? f}
            </span>
          );
        })}
      </div>

      <button
        onClick={onImport}
        className="w-full py-1.5 rounded-lg bg-td-orange hover:bg-td-orange/90 text-white text-xs font-semibold transition-colors"
      >
        Import now
      </button>
    </div>
  );
}
