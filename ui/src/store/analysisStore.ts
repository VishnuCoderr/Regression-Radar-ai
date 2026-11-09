// src/store/analysisStore.ts — History of analyses with localStorage persistence
import { create } from "zustand";
import type { AnalysisRecord } from "../types/api";

const STORAGE_KEY = "regression_radar_history_v1";

function loadInitialRecords(): AnalysisRecord[] {
  if (typeof window === "undefined" || !window.localStorage) return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    // Ignore storage parse issues
  }
  return [];
}

function saveRecords(records: AnalysisRecord[]): void {
  if (typeof window === "undefined" || !window.localStorage) return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
  } catch {
    // Ignore storage quota issues
  }
}

interface AnalysisStore {
  records: AnalysisRecord[];
  selectedRecord: AnalysisRecord | null;
  addRecord: (record: AnalysisRecord) => void;
  selectRecord: (record: AnalysisRecord | null) => void;
  clearRecords: () => void;
}

export const useAnalysisStore = create<AnalysisStore>((set) => ({
  records: loadInitialRecords(),
  selectedRecord: null,
  addRecord: (record) =>
    set((state) => {
      const next = [record, ...state.records.filter((r) => r.id !== record.id)].slice(0, 50);
      saveRecords(next);
      return { records: next };
    }),
  selectRecord: (record) => set({ selectedRecord: record }),
  clearRecords: () => {
    saveRecords([]);
    set({ records: [], selectedRecord: null });
  },
}));
