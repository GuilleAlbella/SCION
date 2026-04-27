"use client";

import Sidebar from "@/components/layout/Sidebar";
import { SelectionProvider } from "@/lib/SelectionContext";
import { ThemeProvider } from "@/lib/ThemeContext";
import { ToastProvider } from "@/components/shared/ToastProvider";
import TaisaWidget from "@/components/shared/TaisaWidget";
import KeyboardShortcuts from "@/components/shared/KeyboardShortcuts";

// Provider composition order is intentional and must NOT be reshuffled:
//   ThemeProvider      → outermost so every child (incl. toasts) can read theme
//   SelectionProvider  → carries the cross-page "active diff pair / snapshot /
//                        change" selection that most pages depend on. Sits
//                        below theme but above toasts so toasts triggered by
//                        selection-aware hooks work.
//   ToastProvider      → innermost provider so both the page tree and the
//                        floating widgets (TaisaWidget) can fire toasts.
// TaisaWidget + KeyboardShortcuts are siblings of the main flex row so they
// render as fixed/portaled overlays on top of any page.
export default function ClientShell({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <SelectionProvider>
        <ToastProvider>
          <div className="flex min-h-screen">
            <Sidebar />
            <div className="flex-1 flex flex-col">{children}</div>
          </div>
          <TaisaWidget />
          <KeyboardShortcuts />
        </ToastProvider>
      </SelectionProvider>
    </ThemeProvider>
  );
}
