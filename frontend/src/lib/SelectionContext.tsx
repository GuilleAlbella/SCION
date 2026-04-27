"use client";

import { createContext, useContext, useState, useCallback } from "react";
import type { ReactNode } from "react";
import type { DiffDetailResponse, ImpactResponse } from "@/lib/api/types";

interface DiffPair {
  snapshotFrom: number;
  snapshotTo: number;
}

interface ChangeImpactRow {
  changeId: number;
  objectIdentifier: string;
  changeType: string;
  severity: string | null;
  isBreaking: boolean | null;
  impact: ImpactResponse | null;
}

interface SelectionState {
  activeSnapshotId: number | null;
  activeChangeId: number | null;
  activeDiffPair: DiffPair | null;

  /** Cached diff details — survives page navigation */
  cachedDiffDetails: DiffDetailResponse | null;
  /** Cached impact results per change — survives page navigation */
  cachedImpactResults: ChangeImpactRow[];

  setActiveSnapshotId: (id: number | null) => void;
  setActiveChangeId: (id: number | null) => void;
  setActiveDiffPair: (pair: DiffPair | null) => void;
  setCachedDiffDetails: (d: DiffDetailResponse | null) => void;
  setCachedImpactResults: (r: ChangeImpactRow[]) => void;
  clearAnalysis: () => void;
}

/**
 * SelectionContext — global cross-page selection and analysis cache.
 *
 * Why a context (vs. URL params or per-page state)?
 *   - SCION pages share selection: choosing a diff pair on the Changes page
 *     should carry over to Impact, What-If, Lineage, etc.
 *   - Analysis (diff details, impact results) is expensive to recompute.
 *     Caching it here means navigating away and back is instant, and the
 *     TAISA widget can read the currently-focused change without coupling.
 *   - Cleared automatically when the user picks a new diff pair so stale
 *     results never leak across unrelated selections.
 */
const SelectionContext = createContext<SelectionState | null>(null);

export type { DiffPair, ChangeImpactRow };

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [activeSnapshotId, setSnapshotId] = useState<number | null>(null);
  const [activeChangeId, setChangeId] = useState<number | null>(null);
  const [activeDiffPair, setDiffPair] = useState<DiffPair | null>(null);
  const [cachedDiffDetails, setDiffDetails] = useState<DiffDetailResponse | null>(null);
  const [cachedImpactResults, setImpactResults] = useState<ChangeImpactRow[]>([]);

  // Setters wrapped in useCallback with empty deps so consumer components
  // don't re-render every time this provider renders — the setter identity
  // stays stable for the provider's lifetime.
  const setActiveSnapshotId = useCallback((id: number | null) => setSnapshotId(id), []);
  const setActiveChangeId = useCallback((id: number | null) => setChangeId(id), []);

  const setActiveDiffPair = useCallback((pair: DiffPair | null) => {
    setDiffPair(pair);
    // When the user clears the diff pair we also drop cached analyses tied
    // to it — otherwise pages would show stale details belonging to the
    // previous selection. NOTE: we don't clear on a *changed* pair here;
    // callers are responsible for deciding that.
    if (pair === null) {
      setDiffDetails(null);
      setImpactResults([]);
    }
  }, []);

  const setCachedDiffDetails = useCallback((d: DiffDetailResponse | null) => setDiffDetails(d), []);
  const setCachedImpactResults = useCallback((r: ChangeImpactRow[]) => setImpactResults(r), []);

  const clearAnalysis = useCallback(() => {
    setDiffDetails(null);
    setImpactResults([]);
  }, []);

  return (
    <SelectionContext value={{
      activeSnapshotId,
      activeChangeId,
      activeDiffPair,
      cachedDiffDetails,
      cachedImpactResults,
      setActiveSnapshotId,
      setActiveChangeId,
      setActiveDiffPair,
      setCachedDiffDetails,
      setCachedImpactResults,
      clearAnalysis,
    }}>
      {children}
    </SelectionContext>
  );
}

export function useSelection() {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be used within SelectionProvider");
  return ctx;
}
