// src/pages/History.tsx — Analysis history page
import { Clock, Trash2, GitBranch } from "lucide-react";
import { Card, CardHeader } from "../components/ui/Card";
import { RiskBadge } from "../components/ui/Badge";
import { useAnalysisStore } from "../store/analysisStore";
import type { AnalysisRecord } from "../types/api";
import { Link } from "react-router-dom";

export function History() {
  const { records, clearRecords } = useAnalysisStore();

  if (records.length === 0) {
    return (
      <div className="p-8 max-w-4xl mx-auto">
        <PageHeader onClear={undefined} />
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-12 h-12 rounded-xl bg-[#18181f] border border-[#2a2a38] flex items-center justify-center mb-4">
            <Clock className="w-6 h-6 text-zinc-600" />
          </div>
          <p className="text-zinc-500 text-sm">No analysis history yet.</p>
          <Link
            to="/analyze"
            className="mt-4 text-sm text-blue-500 hover:text-blue-400 transition-colors"
          >
            Run your first analysis →
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <PageHeader onClear={clearRecords} />
      <Card>
        <CardHeader>
          <div className="grid grid-cols-12 text-xs font-medium text-zinc-600 uppercase tracking-wide">
            <span className="col-span-5">Repository</span>
            <span className="col-span-3">Refs</span>
            <span className="col-span-2 text-right">Score</span>
            <span className="col-span-2 text-right">Time</span>
          </div>
        </CardHeader>
        <div className="divide-y divide-[#1e1e28]">
          {records.map((rec) => (
            <HistoryRow key={rec.id} rec={rec} />
          ))}
        </div>
      </Card>
    </div>
  );
}

function PageHeader({ onClear }: { onClear?: () => void }) {
  return (
    <div className="mb-8 flex items-start justify-between">
      <div>
        <h1 className="text-2xl font-semibold text-white mb-1">Analysis History</h1>
        <p className="text-zinc-500 text-sm">PR risk analyses from this session.</p>
      </div>
      {onClear && (
        <button
          onClick={onClear}
          className="flex items-center gap-1.5 text-xs text-zinc-600 hover:text-red-400 transition-colors"
        >
          <Trash2 className="w-3.5 h-3.5" />
          Clear session
        </button>
      )}
    </div>
  );
}

function HistoryRow({ rec }: { rec: AnalysisRecord }) {
  const name = rec.repo_path.split(/[\\/]/).pop() ?? rec.repo_path;
  const time = new Date(rec.timestamp).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  const score = Math.round(rec.result.overall_score);

  return (
    <div className="grid grid-cols-12 items-center px-5 py-3.5 hover:bg-white/[0.015] transition-colors">
      <div className="col-span-5 min-w-0">
        <span className="text-sm font-medium text-zinc-200 truncate block">{name}</span>
        <span className="text-xs text-zinc-700 font-mono truncate block">{rec.repo_path}</span>
      </div>
      <div className="col-span-3 flex items-center gap-1 text-xs text-zinc-500 font-mono">
        <GitBranch className="w-3 h-3 text-zinc-700" />
        {rec.base_ref} → {rec.head_ref}
      </div>
      <div className="col-span-2 flex items-center justify-end gap-2.5">
        <span className="text-sm font-bold font-mono text-white">{score}</span>
        <RiskBadge category={rec.result.risk_category} />
      </div>
      <div className="col-span-2 text-right text-xs text-zinc-700">{time}</div>
    </div>
  );
}
