"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { globalSearch } from "@/lib/api/search";
import type { SearchResult } from "@/lib/api/types";
import { Search, X, Database, Table2, Columns3, Loader2 } from "lucide-react";

const TYPE_ICONS: Record<string, typeof Database> = {
  SCHEMA: Database,
  TABLE: Table2,
  VIEW: Table2,
  COLUMN: Columns3,
};

/**
 * Command-palette style global search. Opens on Ctrl/Cmd+K or via the trigger
 * button, debounces keystrokes, and routes to the lineage page on select.
 */
export default function GlobalSearch() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const router = useRouter();
  // Stored in a ref (not state) so resetting the timer doesn't re-render.
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Keyboard shortcut: Ctrl+K (Cmd+K on macOS) to open. Bound at the window
  // level so it works regardless of focus. Empty deps — bound once for life.
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setOpen(true);
        // Defer focus until after the modal renders this frame.
        setTimeout(() => inputRef.current?.focus(), 50);
      }
      if (e.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Debounced server search. We wait 300ms after the last keystroke to avoid
  // hammering the backend on every character, and skip queries under 2 chars
  // since they're too noisy to be useful.
  function handleSearch(value: string) {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (value.length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }
    // Show spinner immediately — before the debounce fires.
    setLoading(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const data = await globalSearch(value);
        setResults(data.results);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
  }

  function handleSelect(result: SearchResult) {
    setOpen(false);
    setQuery("");
    setResults([]);
    // Navigate to lineage with the object
    router.push(`/lineage?object=${encodeURIComponent(result.object_name)}&snapshot=${result.snapshot_id}`);
  }

  return (
    <>
      {/* Search trigger button */}
      <button
        onClick={() => {
          setOpen(true);
          setTimeout(() => inputRef.current?.focus(), 50);
        }}
        className="flex items-center gap-2 bg-white/10 hover:bg-white/20 text-white/70 hover:text-white px-3 py-1.5 rounded-lg text-xs transition-colors"
      >
        <Search size={14} />
        <span>Search...</span>
        <kbd className="bg-white/10 px-1.5 py-0.5 rounded text-[10px] font-mono">Ctrl+K</kbd>
      </button>

      {/* Search modal overlay */}
      {open && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-start justify-center pt-[15vh]">
          <div
            ref={containerRef}
            className="bg-white rounded-xl shadow-2xl border border-gray-200 w-full max-w-lg overflow-hidden"
          >
            {/* Input */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200">
              <Search size={18} className="text-td-gray-dark" />
              <input
                ref={inputRef}
                type="text"
                placeholder="Search objects, tables, databases..."
                value={query}
                onChange={(e) => handleSearch(e.target.value)}
                className="flex-1 text-sm outline-none"
              />
              {query && (
                <button onClick={() => { setQuery(""); setResults([]); }}>
                  <X size={16} className="text-td-gray-dark hover:text-td-navy" />
                </button>
              )}
            </div>

            {/* Results */}
            <div className="max-h-80 overflow-y-auto">
              {loading && (
                <div className="px-4 py-6 flex items-center justify-center gap-2 text-sm text-td-gray-dark">
                  <Loader2 size={16} className="animate-spin" />
                  Searching…
                </div>
              )}
              {!loading && results.length === 0 && query.length >= 2 && (
                <div className="px-4 py-6 text-center text-sm text-td-gray-dark">No results found</div>
              )}
              {!loading && results.map((r, idx) => {
                const Icon = TYPE_ICONS[r.object_type] ?? Database;
                return (
                  <button
                    key={`${r.object_name}-${idx}`}
                    onClick={() => handleSelect(r)}
                    className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 text-left transition-colors border-b border-gray-100 last:border-0"
                  >
                    <Icon size={16} className="text-td-navy shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-td-navy truncate">{r.object_name}</div>
                      <div className="text-xs text-td-gray-dark truncate">{r.context}</div>
                    </div>
                    <span className="bg-td-navy/10 text-td-navy px-2 py-0.5 rounded text-[10px] font-medium shrink-0">
                      {r.object_type}
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Footer */}
            <div className="px-4 py-2 border-t border-gray-200 bg-gray-50 flex items-center gap-4 text-[10px] text-td-gray-dark">
              <span><kbd className="bg-white px-1 py-0.5 rounded border border-gray-200 font-mono">↑↓</kbd> navigate</span>
              <span><kbd className="bg-white px-1 py-0.5 rounded border border-gray-200 font-mono">↵</kbd> select</span>
              <span><kbd className="bg-white px-1 py-0.5 rounded border border-gray-200 font-mono">esc</kbd> close</span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
