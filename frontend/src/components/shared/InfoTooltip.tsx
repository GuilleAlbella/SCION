"use client";

import { useState, useRef, useEffect } from "react";
import { HelpCircle } from "lucide-react";

interface InfoTooltipProps {
  text: string;
  /** Optional longer explanation shown as secondary text. */
  detail?: string;
  /** Icon size in pixels (default 12). */
  size?: number;
  /** Tailwind color class for the icon (default text-td-gray-dark). */
  className?: string;
}

/**
 * Accessible info tooltip. Click or hover on the ? icon to see the explanation.
 * Used to clarify metrics and terms throughout SCION.
 */
export default function InfoTooltip({ text, detail, size = 12, className = "text-td-gray-dark/60" }: InfoTooltipProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLSpanElement>(null);

  // Close on outside click — covers the click-to-open path (hover naturally
  // closes on mouse-leave). Only attaches the listener while open to avoid
  // unnecessary global listeners.
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <span
      ref={containerRef}
      className="relative inline-flex items-center"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen((prev) => !prev); }}
        className={`cursor-help hover:text-td-navy transition-colors ${className}`}
        aria-label="More information"
      >
        <HelpCircle size={size} />
      </button>

      {open && (
        <span
          role="tooltip"
          className="absolute z-50 left-full ml-2 top-1/2 -translate-y-1/2 w-64 bg-slate-900 text-white text-[11px] rounded-lg shadow-lg p-3 pointer-events-none"
        >
          <span className="block font-medium leading-relaxed">{text}</span>
          {detail && <span className="block text-slate-300 mt-1 leading-relaxed">{detail}</span>}
          {/* Little arrow */}
          <span
            className="absolute top-1/2 -translate-y-1/2 -left-1 w-2 h-2 bg-slate-900 rotate-45"
          />
        </span>
      )}
    </span>
  );
}
