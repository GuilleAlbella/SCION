"use client";

import { createContext, useContext, useState, useCallback } from "react";
import type { ReactNode } from "react";
import { CheckCircle, AlertTriangle, Info, X } from "lucide-react";

interface Toast {
  id: number;
  message: string;
  type: "success" | "error" | "info";
  exiting?: boolean;
}

interface ToastContextType {
  toast: (message: string, type?: "success" | "error" | "info") => void;
}

const ToastContext = createContext<ToastContextType>({ toast: () => {} });

// Module-level monotonic counter for toast IDs. Module scope (not state) so
// IDs stay unique across re-renders and remain simple to reason about.
let toastId = 0;

/**
 * ToastProvider — lightweight toast system. Mount once near the app root
 * and call `useToast().toast("msg", "success")` from anywhere.
 * Two-phase removal: mark as exiting for the CSS exit animation, then
 * actually remove from state once the animation completes.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((message: string, type: "success" | "error" | "info" = "success") => {
    const id = ++toastId;
    setToasts((prev) => [...prev, { id, message, type }]);
    // Two-stage auto-dismiss: after 4s we mark it exiting so the CSS exit
    // animation plays, then 200ms later we actually drop it from state.
    setTimeout(() => {
      setToasts((prev) => prev.map((t) => t.id === id ? { ...t, exiting: true } : t));
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 200);
    }, 4000);
  }, []);

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.map((t) => t.id === id ? { ...t, exiting: true } : t));
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 200);
  }, []);

  const ICONS = {
    success: <CheckCircle size={16} className="text-green-400" />,
    error: <AlertTriangle size={16} className="text-red-400" />,
    info: <Info size={16} className="text-blue-400" />,
  };

  const BG = {
    success: "bg-green-900/90 border-green-700",
    error: "bg-red-900/90 border-red-700",
    info: "bg-blue-900/90 border-blue-700",
  };

  return (
    <ToastContext value={{ toast: addToast }}>
      {children}
      {/* Toast container */}
      <div className="fixed bottom-6 right-6 z-[100] flex flex-col gap-2 pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`${t.exiting ? "toast-exit" : "toast-enter"} pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl border backdrop-blur-sm shadow-lg ${BG[t.type]}`}
          >
            {ICONS[t.type]}
            <span className="text-sm text-white font-medium">{t.message}</span>
            <button
              onClick={() => removeToast(t.id)}
              className="ml-2 text-white/50 hover:text-white transition-colors"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
