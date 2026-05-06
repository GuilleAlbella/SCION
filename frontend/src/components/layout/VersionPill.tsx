"use client";

/**
 * Sidebar footer version display.
 *
 * Shows the current SCION version always; when a newer GitHub release
 * exists, swaps to a green "update available" pill that links to the
 * release page. Pure read-only — the actual upgrade is handled by
 * Watchtower in the background (or `update.sh` for the impatient).
 *
 * Polls `/api/v1/system/version` once on mount. The endpoint itself
 * caches the GitHub answer for 1h so multiple tabs / sessions don't
 * thrash the upstream API.
 */

import { useEffect, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import client from "@/lib/api/client";
import { APP_VERSION, APP_STAGE } from "@/lib/constants";

type VersionInfo = {
  current: string;
  latest: string | null;
  update_available: boolean;
  release_url: string | null;
  release_name: string | null;
  published_at: string | null;
};

export default function VersionPill() {
  const [info, setInfo] = useState<VersionInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Best-effort fetch. We deliberately swallow errors — a missing
    // backend or rate-limited GitHub must never break the Sidebar.
    client
      .get<VersionInfo>("/system/version")
      .then((res) => {
        if (!cancelled) setInfo(res.data);
      })
      .catch(() => {
        // Silent: keep the static APP_VERSION fallback.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Update available — green pill, clickable, opens release notes.
  if (info?.update_available && info.release_url) {
    return (
      <a
        href={info.release_url}
        target="_blank"
        rel="noopener noreferrer"
        className="group flex items-center gap-1.5 text-[10px]"
        title={`New release: ${info.latest}. Click to view release notes.`}
      >
        {APP_STAGE && (
          <span className="bg-td-orange/20 text-td-orange px-1.5 py-0.5 rounded text-[9px] font-bold">
            {APP_STAGE}
          </span>
        )}
        <span className="text-white/40">{APP_VERSION}</span>
        <span className="bg-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded font-semibold flex items-center gap-0.5 group-hover:bg-emerald-500/30 transition-colors">
          {info.latest} available
          <ArrowUpRight size={9} />
        </span>
      </a>
    );
  }

  // Default footer (current state, or update info still loading).
  return (
    <div className="text-[10px] text-white/40">
      {APP_STAGE && (
        <span className="bg-td-orange/20 text-td-orange px-1.5 py-0.5 rounded text-[9px] font-bold">
          {APP_STAGE}
        </span>
      )}
      <span className="ml-1.5">{APP_VERSION}</span>
    </div>
  );
}
