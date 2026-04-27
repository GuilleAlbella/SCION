"use client";

import { createContext, useContext, useState, useCallback, useEffect } from "react";
import type { ReactNode } from "react";

interface ThemeState {
  dark: boolean;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeState>({ dark: false, toggle: () => {} });

/**
 * ThemeProvider — light/dark toggle persisted in localStorage.
 * The dark class is added to <html> (documentElement) so Tailwind's
 * `dark:` variants apply globally without prop drilling.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  // Default to light on first load; the effect below upgrades to dark if
  // the user previously chose it. We intentionally start with `false` (not
  // reading localStorage synchronously) to avoid SSR hydration mismatch.
  const [dark, setDark] = useState(false);

  // Load preference from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem("scion-theme");
    if (saved === "dark") {
      setDark(true);
      document.documentElement.classList.add("dark");
    }
  }, []);

  const toggle = useCallback(() => {
    setDark((prev) => {
      const next = !prev;
      if (next) {
        document.documentElement.classList.add("dark");
        localStorage.setItem("scion-theme", "dark");
      } else {
        document.documentElement.classList.remove("dark");
        localStorage.setItem("scion-theme", "light");
      }
      return next;
    });
  }, []);

  return (
    <ThemeContext value={{ dark, toggle }}>
      {children}
    </ThemeContext>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
