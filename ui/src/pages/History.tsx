// src/pages/History.tsx — Analysis history page with expandable reports
import { useState } from "react";
import {
  Clock, Trash2, GitBranch, ChevronDown, ChevronUp, ExternalLink,
  TestTube2, Users,
} from "lucide-react";
import { useNavigate, Link } from "react-router-dom";
import { Card, CardHeader } from "../components/ui/Card";
import { RiskBadge } from "../components/ui/Badge";
import { ScoreGauge } from "../components/ui/ScoreGauge";
import { SignalBar } from "../components/ui/SignalBar";
import { useAnalysisStore } from "../store/analysisStore";
import type { AnalysisRecord } from "../types/api";

const SIGNAL_LABELS: Record<string, string> = {
  historical_hotspot: "Historical Hotspot",
  cochange_anomaly: "Co-change Anomaly",
  test_gap: "Test Gap",
  ownership: "Ownership Risk",
};

export function History() {
  const { records, clearRecords, selectRecord } = useAnalysisStore();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const navigate = useNavigate();

  function handleOpenInAnalyze(rec: AnalysisRecord) {
    selectRecord(rec);
    navigate("/analyze");
  }

  function toggleExpand(id: string) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

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
            <HistoryRow
              key={rec.id}
              rec={rec}
              isExpanded={expandedId === rec.id}
              onToggle={() => toggleExpand(rec.id)}
              onOpen={() => handleOpenInAnalyze(rec)}
            />
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
        <p className="text-zinc-500 text-sm">PR risk analyses persisted across browser sessions.</p>
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

function HistoryRow({
  rec,
  isExpanded,
  onToggle,
  onOpen,
}: {
  rec: AnalysisRecord;
  isExpanded: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  const name = rec.repo_path.split(/[\\/]/).pop() ?? rec.repo_path;
  const time = new Date(rec.timestamp).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  const score = Math.round(rec.result.overall_score);

  return (
    <div className="transition-colors hover:bg-white/[0.015]">
      {/* Row header */}
      <div
        onClick={onToggle}
        className="grid grid-cols-12 items-center px-5 py-3.5 cursor-pointer select-none"
      >
        <div className="col-span-5 min-w-0 pr-2">
          <div className="flex items-center gap-1.5">
            {isExpanded ? (
              <ChevronUp className="w-3.5 h-3.5 text-zinc-500 flex-shrink-0" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5 text-zinc-500 flex-shrink-0" />
            )}
            <span className="text-sm font-medium text-zinc-200 truncate">{name}</span>
          </div>
          <span className="text-xs text-zinc-600 font-mono truncate block pl-5">{rec.repo_path}</span>
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

      {/* Expanded report viewer */}
      {isExpanded && (
        <div className="px-5 pb-5 pt-2 border-t border-[#1e1e28] bg-[#14141c]/50">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-4 text-xs text-zinc-500">
              <span>{rec.result.total_files_changed} files changed</span>
              <span className="text-emerald-400">+{rec.result.additions}</span>
              <span className="text-red-400">-{rec.result.deletions}</span>
            </div>
            <button
              type="button"
              onClick={onOpen}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600/10 hover:bg-blue-600/20 text-blue-400 border border-blue-600/20 transition-colors"
            >
              <ExternalLink className="w-3 h-3" />
              Open in PR Intelligence
            </button>
          </div>

          <div className="grid md:grid-cols-3 gap-4 mb-4">
            <div className="flex flex-col items-center justify-center p-4 rounded-xl bg-[#18181f] border border-[#2a2a38]">
              <ScoreGauge
                score={rec.result.overall_score}
                category={rec.result.risk_category}
                size={110}
              />
              <div className="mt-2 text-center">
                <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wide">
                  Risk Category
                </span>
                <div className="mt-1">
                  <RiskBadge category={rec.result.risk_category} />
                </div>
              </div>
            </div>

            <div className="md:col-span-2 p-4 rounded-xl bg-[#18181f] border border-[#2a2a38]">
              <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2.5">
                Why was this flagged?
              </h4>
              <ul className="space-y-2">
                {rec.result.why_flagged.map((reason, i) => (
                  <li key={i} className="text-xs text-zinc-300 flex items-start gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-400 mt-1.5 flex-shrink-0" />
                    <span>{reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Signals Breakdown */}
          <div className="p-4 rounded-xl bg-[#18181f] border border-[#2a2a38] mb-4">
            <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">
              Signal Breakdown
            </h4>
            <div className="divide-y divide-[#2a2a38]">
              {Object.entries(rec.result.signals).map(([key, sig]) => (
                <SignalBar
                  key={key}
                  label={SIGNAL_LABELS[key] ?? key}
                  score={sig.score}
                  weight={rec.result.weights[key] ?? 0.25}
                  available={sig.is_available}
                  explanation={sig.explanation}
                />
              ))}
            </div>
          </div>

          {/* Recommended actions */}
          <div className="p-4 rounded-xl bg-[#18181f] border border-[#2a2a38]">
            <h4 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">
              Recommended Actions
            </h4>
            <div className="space-y-3">
              {rec.result.recommended_actions.tests_to_run.length > 0 && (
                <div className="flex items-start gap-2 text-xs">
                  <TestTube2 className="w-3.5 h-3.5 text-blue-400 mt-0.5 flex-shrink-0" />
                  <div>
                    <span className="font-semibold text-zinc-300">Run Tests: </span>
                    <span className="text-zinc-400 font-mono">
                      {rec.result.recommended_actions.tests_to_run.join(", ")}
                    </span>
                  </div>
                </div>
              )}
              {rec.result.recommended_actions.suggested_reviewers.length > 0 && (
                <div className="flex items-start gap-2 text-xs">
                  <Users className="w-3.5 h-3.5 text-emerald-400 mt-0.5 flex-shrink-0" />
                  <div>
                    <span className="font-semibold text-zinc-300">Suggested Reviewers: </span>
                    <span className="text-zinc-400">
                      {rec.result.recommended_actions.suggested_reviewers.join(", ")}
                    </span>
                  </div>
                </div>
              )}
              {rec.result.recommended_actions.summary && (
                <p className="text-xs text-zinc-400 leading-relaxed border-t border-[#2a2a38] pt-2">
                  {rec.result.recommended_actions.summary}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
