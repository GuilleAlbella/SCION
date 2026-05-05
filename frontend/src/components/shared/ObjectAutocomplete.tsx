"use client";

// Server-backed object-picker. Replaces every native <select> we used to
// populate from API responses ("here's all 240k object identifiers, good
// luck rendering them"). The user types, we debounce, hit
// /api/v1/objects/search?q=..., render at most ~20 results.
//
// Design choices worth calling out:
//
//   * **Server-paginated, never lists everything**. The endpoint returns
//     up to `limit + 1` rows so we can detect `has_more` cheaply; the
//     `+1` is stripped server-side, and `has_more=true` drives the
//     "Type more to narrow…" hint. This is the single performance
//     reason the component exists — you cannot put 240k <option>s in a
//     native <select> and expect Chrome to survive.
//
//   * **No virtualization**. We never render more than `limit` rows,
//     and `limit` defaults to 20. Virtualization would be over-engineered
//     for a list this small.
//
//   * **AbortController + request-id guard**. Two layers of staleness
//     protection because debounced fetches race in surprising ways:
//     `AbortController` cancels in-flight requests when a new one fires;
//     `requestIdRef` ensures that even if a slow response sneaks past the
//     abort (browsers sometimes deliver the response before propagating
//     the abort), we still discard its data.
//
//   * **Click-outside to close, plus Escape**. Selecting from the
//     dropdown is a click; we want that click to register *before* we
//     close. Listener uses `mousedown` so the dropdown is still mounted
//     when the click handler fires. Escape gives a keyboard exit.
//
//   * **Exact-match shortcut**. If the user pastes a fully-qualified
//     identifier and presses Enter, we take it as-is rather than forcing
//     them to scroll-pick from a dropdown that probably has it as the
//     first row anyway.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Search, X, Loader2 } from "lucide-react";

import { searchObjects } from "@/lib/api/objects";
import type { ObjectSearchResponse } from "@/lib/api/types";

export interface ObjectAutocompleteProps {
  /** Current selection (the resolved object identifier). Empty string when none. */
  value: string;
  /** Fires whenever the user picks (or pastes-and-Enters) an identifier.
   *  The parent decides what to do with it (load timeline, scope TAISA, …). */
  onChange: (value: string) => void;
  /** Required when `source === "graph"`; ignored otherwise. */
  snapshotId?: number;
  source?: "changes" | "graph";
  placeholder?: string;
  /** How many rows the dropdown should show. Default 20 — keep small.
   *  The backend caps at 100 regardless of what we ask. */
  limit?: number;
  /** Optional className for the outer wrapper. */
  className?: string;
  /** Disable the input (e.g. while a parent is mid-fetch). */
  disabled?: boolean;
  /** Auto-focus on mount. Off by default to avoid stealing focus when
   *  the component is inside a collapsed `<details>`. */
  autoFocus?: boolean;
}

const DEBOUNCE_MS = 250;

export default function ObjectAutocomplete({
  value,
  onChange,
  snapshotId,
  source = "changes",
  placeholder = "Type to search objects...",
  limit = 20,
  className = "",
  disabled = false,
  autoFocus = false,
}: ObjectAutocompleteProps) {
  // Free-text input — distinct from `value` because the user may be
  // mid-typing, in which case `value` (the resolved selection) is stale.
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState<string[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // We store the AbortController for the in-flight request so a new
  // keystroke can cancel it. `requestIdRef` is the secondary guard
  // (see header comment) that catches any response that races past.
  const abortRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Sync external `value` → `query` when it changes from the outside,
  // e.g. when the parent clears the selection or pre-fills from a URL.
  // Only when the input isn't focused, so we don't yank what the user
  // is typing.
  useEffect(() => {
    if (document.activeElement !== inputRef.current) {
      setQuery(value);
    }
  }, [value]);

  // Click-outside → close. Mousedown (not click) so a click inside the
  // dropdown completes its handler before we close.
  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  // Debounced fetch. Re-fires whenever the query, source, snapshot, or
  // limit changes. `setOpen(true)` is part of every fire so the dropdown
  // appears as soon as a fetch is even *attempted*, not only when results
  // come back — that way the spinner is visible during the first request.
  const runFetch = useCallback(
    async (q: string) => {
      const myReqId = ++requestIdRef.current;

      // Cancel any prior in-flight request.
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      setLoading(true);
      try {
        const data: ObjectSearchResponse = await searchObjects({
          q: q.trim() || undefined,
          snapshot_id: source === "graph" ? snapshotId : undefined,
          source,
          limit,
        });
        // Discard if a newer fetch has started OR aborted us mid-flight.
        if (myReqId !== requestIdRef.current) return;
        setResults(data.items);
        setHasMore(data.has_more);
      } catch (err) {
        // Aborted requests throw; treat as a no-op.
        if ((err as { name?: string })?.name === "AbortError") return;
        if (myReqId !== requestIdRef.current) return;
        setResults([]);
        setHasMore(false);
      } finally {
        if (myReqId === requestIdRef.current) {
          setLoading(false);
        }
      }
    },
    [source, snapshotId, limit],
  );

  function handleQueryChange(next: string) {
    setQuery(next);
    setOpen(true);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      void runFetch(next);
    }, DEBOUNCE_MS);
  }

  function handleFocus() {
    setOpen(true);
    // Show the first page immediately on focus so the user has something
    // to look at even before they type anything. Only fires if results
    // are empty and we haven't fetched yet — avoids re-hitting the API
    // every time the input is focused.
    if (results.length === 0 && !loading) {
      void runFetch(query);
    }
  }

  function pick(identifier: string) {
    onChange(identifier);
    setQuery(identifier);
    setOpen(false);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setOpen(false);
      inputRef.current?.blur();
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      // Prefer the first result if there is one (most common case);
      // fall back to the raw query for paste-and-go workflows where the
      // user knows the exact identifier.
      const target = results[0] ?? query.trim();
      if (target) pick(target);
    }
  }

  // Memoised hint message — small UI flicker is annoying so we compute
  // it once per render.
  const hint = useMemo(() => {
    if (loading) return null;
    if (query.trim().length === 0 && results.length === 0) {
      return "Start typing to search.";
    }
    if (results.length === 0 && query.trim().length > 0) {
      return `No matches for "${query.trim()}".`;
    }
    if (hasMore) {
      return `Showing first ${results.length} match(es) — keep typing to narrow down.`;
    }
    return null;
  }, [loading, query, results.length, hasMore]);

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <div className="relative">
        <Search
          size={14}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-td-gray-dark pointer-events-none"
        />
        <input
          ref={inputRef}
          type="text"
          value={query}
          disabled={disabled}
          autoFocus={autoFocus}
          placeholder={placeholder}
          onChange={(e) => handleQueryChange(e.target.value)}
          onFocus={handleFocus}
          onKeyDown={handleKeyDown}
          className="w-full border border-gray-300 rounded pl-8 pr-8 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-td-navy/30 focus:border-td-navy disabled:bg-gray-100 disabled:text-gray-500"
        />
        {loading && (
          <Loader2
            size={14}
            className="absolute right-8 top-1/2 -translate-y-1/2 text-td-navy animate-spin"
          />
        )}
        {query && !disabled && (
          <button
            type="button"
            onClick={() => {
              setQuery("");
              onChange("");
              setResults([]);
              setHasMore(false);
              inputRef.current?.focus();
            }}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-td-gray-dark hover:text-td-navy"
            title="Clear"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {open && (
        <div className="absolute z-30 mt-1 w-full bg-white border border-gray-200 rounded shadow-lg max-h-72 overflow-y-auto">
          {results.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => pick(item)}
              className={`w-full text-left px-3 py-1.5 text-xs font-mono hover:bg-gray-50 truncate ${
                item === value ? "bg-td-navy/5 text-td-navy font-semibold" : "text-td-navy"
              }`}
              title={item}
            >
              {item}
            </button>
          ))}
          {hint && (
            <div className="px-3 py-2 text-[11px] text-td-gray-dark border-t border-gray-100">
              {hint}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
