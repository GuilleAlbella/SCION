"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { X, Keyboard } from "lucide-react";

const SHORTCUTS = [
  { keys: ["Ctrl", "K"], action: "Global search", route: null },
  { keys: ["?"], action: "Show shortcuts", route: null },
  { keys: ["G", "D"], action: "Go to Dashboard", route: "/" },
  { keys: ["G", "C"], action: "Go to Changes", route: "/changes" },
  { keys: ["G", "I"], action: "Go to Impact", route: "/impact" },
  { keys: ["G", "W"], action: "Go to What-If", route: "/simulation" },
  { keys: ["G", "L"], action: "Go to Lineage", route: "/lineage" },
  { keys: ["G", "A"], action: "Go to Alerts", route: "/alerts" },
  { keys: ["G", "T"], action: "Go to Timeline", route: "/timeline" },
];

/**
 * Global keyboard shortcuts. Supports Vim-style "chord" navigation: press
 * "g" followed by a second key (within 1s) to jump to the matching page.
 * "?" toggles the help overlay.
 */
export default function KeyboardShortcuts() {
  const [showHelp, setShowHelp] = useState(false);
  // True while we're in the "G was just pressed" window, waiting for the
  // second key of a G+X chord.
  const [pendingG, setPendingG] = useState(false);
  const router = useRouter();

  useEffect(() => {
    // Timer that closes the G+X chord window. Declared per-effect so cleanup
    // can cancel it on unmount.
    let gTimer: ReturnType<typeof setTimeout>;

    function handleKeyDown(e: KeyboardEvent) {
      // Never hijack keys while the user is typing into a form control,
      // otherwise "g" would trigger navigation mid-word.
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (e.key === "?") {
        e.preventDefault();
        setShowHelp((prev) => !prev);
        return;
      }

      if (e.key === "Escape") {
        setShowHelp(false);
        setPendingG(false);
        return;
      }

      // G+X navigation — first half of the chord. Start a 1s window during
      // which the next key will be interpreted as the chord's second key.
      if (e.key === "g" && !pendingG) {
        setPendingG(true);
        gTimer = setTimeout(() => setPendingG(false), 1000);
        return;
      }

      // Second half of the chord: match against the shortcuts table and
      // navigate if recognized. Unknown second keys just cancel the chord.
      if (pendingG) {
        setPendingG(false);
        clearTimeout(gTimer);
        const combo = `G${e.key.toUpperCase()}`;
        const shortcut = SHORTCUTS.find((s) => s.keys.join("") === combo);
        if (shortcut?.route) {
          e.preventDefault();
          router.push(shortcut.route);
        }
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      clearTimeout(gTimer);
    };
  }, [pendingG, router]);

  if (!showHelp) return null;

  return (
    <div className="fixed inset-0 bg-black/50 z-[150] flex items-center justify-center" onClick={() => setShowHelp(false)}>
      <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-slate-700 w-full max-w-md overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-slate-700">
          <div className="flex items-center gap-2">
            <Keyboard size={16} className="text-td-navy" />
            <h3 className="text-sm font-semibold text-td-navy">Keyboard Shortcuts</h3>
          </div>
          <button onClick={() => setShowHelp(false)} className="text-td-gray-dark hover:text-td-navy">
            <X size={16} />
          </button>
        </div>
        <div className="p-4 space-y-1.5 max-h-[400px] overflow-y-auto">
          {SHORTCUTS.map((s) => (
            <div key={s.action} className="flex items-center justify-between py-1.5">
              <span className="text-xs text-gray-700 dark:text-slate-300">{s.action}</span>
              <div className="flex gap-1">
                {s.keys.map((k) => (
                  <kbd key={k} className="bg-gray-100 dark:bg-slate-800 border border-gray-200 dark:border-slate-600 text-td-navy dark:text-slate-300 px-2 py-0.5 rounded text-[11px] font-mono font-medium min-w-[24px] text-center">
                    {k}
                  </kbd>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="px-5 py-2.5 border-t border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-800/50 text-[10px] text-td-gray-dark text-center">
          Press <kbd className="bg-white dark:bg-slate-700 px-1.5 py-0.5 rounded border border-gray-200 dark:border-slate-600 font-mono">?</kbd> to toggle this panel
        </div>
      </div>
    </div>
  );
}
