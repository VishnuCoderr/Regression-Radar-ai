// src/store/analysisStore.ts — In-memory history of analyses this session
import { create } from "zustand";
import type { AnalysisRecord } from "../types/api";

interface AnalysisStore {
  records: AnalysisRecord[];
  addRecord: (record: AnalysisRecord) => void;
  clearRecords: () => void;
}

export const useAnalysisStore = create<AnalysisStore>((set) => ({
  records: [],
  addRecord: (record) =>
    set((state) => ({ records: [record, ...state.records].slice(0, 50) })),
  clearRecords: () => set({ records: [] }),
}));
