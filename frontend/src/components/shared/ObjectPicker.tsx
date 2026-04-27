"use client";

/**
 * ObjectPicker — hierarchical + searchable picker for warehouse objects.
 *
 * Addresses a gap raised in Meeting #7 by Rahul (filter/narrow objects in
 * lineage) and Kindy (hierarchy: database → table → column is the mental
 * model customers already have). For 500M-relationship-sized warehouses
 * (Lloyds Bank scale), a plain <select> is unusable.
 *
 * Two modes, both active at the same time:
 *   1. Free-text search — matches anywhere in the fully-qualified name.
 *   2. Drill-down tree — `database > table/view/proc`, expandable.
 *
 * Keep this component self-contained: no SWR, no API calls. It just takes
 * an array of fully-qualified object names + a value + onChange. The parent
 * (Lineage, Impact, Graph) is responsible for building the list.
 */

import { useMemo, useState, useRef, useEffect } from "react";
import { Search, ChevronRight, ChevronDown, Database, Table, Eye, Code2, X } from "lucide-react";

export interface ObjectEntry {
  /** Fully-qualified name, e.g. `core_banking.transactions`. */
  name: string;
  /** Object type so we can pick an icon. */
  type?: string;
}

interface Props {
  /** All candidate objects. Pre-filtered by the parent (e.g. exclude internal). */
  objects: ObjectEntry[];
  value: string | null;
  onChange: (name: string | null) => void;
  placeholder?: string;
  /** When true, the picker renders inline (not in a popover). Good for
   *  always-visible sidebars; defaults to popover behaviour. */
  inline?: boolean;
}

// Pick an icon for the object type. Keep the mapping narrow — anything we
// don't know about falls back to a generic table icon.
function iconFor(type?: string) {
  const t = (type || "").toUpperCase();
  if (t === "VIEW") return Eye;
  if (t === "STORED_PROCEDURE" || t === "MACRO" || t === "FUNCTION" || t === "UDF" || t === "TRIGGER") return Code2;
  if (t === "DATABASE" || t === "SCHEMA") return Database;
  return Table;
}

export default function ObjectPicker({ objects, value, onChange, placeholder = "Search object or browse by database...", inline = false }: Props) {
  const [open, setOpen] = useState(inline);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Group by database prefix (text before the first dot). Objects with no
  // dot are put in an "(ungrouped)" bucket so they're still reachable via
  // the tree, not only via search.
  const grouped = useMemo(() => {
    const m = new Map<string, ObjectEntry[]>();
    for (const o of objects) {
      const dot = o.name.indexOf(".");
      const db = dot > 0 ? o.name.slice(0, dot) : "(ungrouped)";
      if (!m.has(db)) m.set(db, []);
      m.get(db)!.push(o);
    }
    // Stable alphabetical order — users scanning "core_banking" shouldn't
    // see it jump around between renders.
    return [...m.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([db, items]) => [db, items.sort((a, b) => a.name.localeCompare(b.name))] as const);
  }, [objects]);

  // Search is case-insensitive substring on the full name. Intentionally
  // dumb — fancy fuzzy matching is a trap at this scale (users typed
  // "core" because they want "core*", not "clearing_engine").
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    return objects
      .filter((o) => o.name.toLowerCase().includes(q))
      .slice(0, 50); // hard cap so a one-char query doesn't render 10k rows
  }, [objects, query]);

  // Auto-expand the database containing the current value so the user sees
  // it highlighted in the tree when they reopen the picker.
  useEffect(() => {
    if (value) {
      const dot = value.indexOf(".");
      if (dot > 0) {
        setExpanded((prev) => {
          const next = new Set(prev);
          next.add(value.slice(0, dot));
          return next;
        });
      }
    }
  }, [value]);

  // Click-outside closes the popover. Inline mode skips this.
  useEffect(() => {
    if (inline) return;
    function onDoc(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [inline]);

  function toggle(db: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(db)) next.delete(db);
      else next.add(db);
      return next;
    });
  }

  function pick(name: string) {
    onChange(name);
    setQuery("");
    if (!inline) setOpen(false);
  }

  const panel = (
    <div className={inline ? "" : "absolute z-20 left-0 right-0 top-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-96 overflow-hidden flex flex-col"}>
      {/* Search box — always visible at top of the panel. */}
      <div className="p-2 border-b border-gray-100 bg-gray-50">
        <div className="relative">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            autoFocus={!inline}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type to search across all objects..."
            className="w-full pl-7 pr-7 py-1.5 text-xs border border-gray-300 rounded bg-white"
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              aria-label="Clear search"
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      {/* Body: either flat search results OR the grouped tree. */}
      <div className="overflow-y-auto flex-1" style={{ maxHeight: inline ? 320 : 320 }}>
        {filtered ? (
          filtered.length === 0 ? (
            <div className="px-3 py-6 text-center text-xs text-gray-500">
              No objects match <span className="font-mono">&quot;{query}&quot;</span>
            </div>
          ) : (
            <>
              <div className="px-3 py-1.5 text-[10px] uppercase tracking-wide text-gray-500 bg-gray-50 sticky top-0 border-b border-gray-100">
                {filtered.length} match{filtered.length === 1 ? "" : "es"}
                {filtered.length === 50 && " (showing first 50 — refine your search)"}
              </div>
              <ul>
                {filtered.map((o) => {
                  const Icon = iconFor(o.type);
                  const isSel = o.name === value;
                  return (
                    <li key={o.name}>
                      <button
                        onClick={() => pick(o.name)}
                        className={`w-full text-left px-3 py-1.5 text-xs font-mono flex items-center gap-2 hover:bg-blue-50 ${isSel ? "bg-blue-100 text-blue-900 font-semibold" : "text-gray-700"}`}
                      >
                        <Icon size={12} className="text-gray-400 shrink-0" />
                        <span className="truncate">{o.name}</span>
                        {o.type && <span className="ml-auto text-[9px] text-gray-400 uppercase">{o.type}</span>}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )
        ) : (
          <ul>
            {grouped.map(([db, items]) => {
              const isExp = expanded.has(db);
              return (
                <li key={db}>
                  <button
                    onClick={() => toggle(db)}
                    className="w-full text-left px-2 py-1.5 text-xs flex items-center gap-1 hover:bg-gray-50 border-b border-gray-100"
                  >
                    {isExp ? <ChevronDown size={12} className="text-gray-500" /> : <ChevronRight size={12} className="text-gray-500" />}
                    <Database size={12} className="text-blue-500" />
                    <span className="font-semibold text-gray-800">{db}</span>
                    <span className="ml-auto text-[10px] text-gray-400">{items.length}</span>
                  </button>
                  {isExp && (
                    <ul className="bg-gray-50/50">
                      {items.map((o) => {
                        const Icon = iconFor(o.type);
                        const isSel = o.name === value;
                        const leaf = o.name.includes(".") ? o.name.slice(o.name.indexOf(".") + 1) : o.name;
                        return (
                          <li key={o.name}>
                            <button
                              onClick={() => pick(o.name)}
                              className={`w-full text-left pl-8 pr-3 py-1 text-xs font-mono flex items-center gap-2 hover:bg-blue-50 ${isSel ? "bg-blue-100 text-blue-900 font-semibold" : "text-gray-700"}`}
                            >
                              <Icon size={11} className="text-gray-400 shrink-0" />
                              <span className="truncate">{leaf}</span>
                              {o.type && <span className="ml-auto text-[9px] text-gray-400 uppercase">{o.type}</span>}
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </li>
              );
            })}
            {grouped.length === 0 && (
              <div className="px-3 py-6 text-center text-xs text-gray-500">No objects available.</div>
            )}
          </ul>
        )}
      </div>

      {/* Footer helper */}
      <div className="px-3 py-1.5 border-t border-gray-100 bg-gray-50 text-[10px] text-gray-500 flex items-center justify-between">
        <span>{objects.length} objects total</span>
        {value && (
          <button
            onClick={() => { onChange(null); setQuery(""); }}
            className="text-blue-600 hover:underline"
          >
            Clear selection
          </button>
        )}
      </div>
    </div>
  );

  if (inline) {
    return (
      <div className="border border-gray-200 rounded-lg bg-white overflow-hidden">
        {panel}
      </div>
    );
  }

  return (
    <div className="relative" ref={wrapperRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm bg-white text-left flex items-center gap-2 hover:border-gray-400"
      >
        <Search size={12} className="text-gray-400 shrink-0" />
        <span className={`truncate ${value ? "font-mono text-gray-800" : "text-gray-400"}`}>
          {value ?? placeholder}
        </span>
        <ChevronDown size={12} className={`ml-auto text-gray-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && panel}
    </div>
  );
}
