// src/components/ui/SignalBar.tsx — Horizontal signal score bar
interface SignalBarProps {
  label: string;
  score: number;
  weight: number;
  available: boolean;
  explanation: string;
}

function barColor(score: number): string {
  if (score >= 80) return "bg-red-500";
  if (score >= 60) return "bg-orange-500";
  if (score >= 30) return "bg-amber-500";
  return "bg-emerald-500";
}

export function SignalBar({ label, score, weight, available, explanation }: SignalBarProps) {
  if (!available) {
    return (
      <div className="py-3 border-b border-[#2a2a38] last:border-0">
        <div className="flex justify-between items-center mb-1.5">
          <span className="text-sm font-medium text-zinc-300">{label}</span>
          <span className="text-xs text-zinc-600 font-mono">N/A — insufficient history</span>
        </div>
        <p className="text-xs text-zinc-600">{explanation}</p>
      </div>
    );
  }
  return (
    <div className="py-3 border-b border-[#2a2a38] last:border-0">
      <div className="flex justify-between items-center mb-2">
        <span className="text-sm font-medium text-zinc-200">{label}</span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500">weight {Math.round(weight * 100)}%</span>
          <span className="text-sm font-bold font-mono text-white">{Math.round(score)}</span>
        </div>
      </div>
      <div className="h-1.5 bg-[#2a2a38] rounded-full overflow-hidden mb-2">
        <div
          className={`h-full rounded-full ${barColor(score)}`}
          style={{ width: `${score}%`, transition: "width 0.5s ease" }}
        />
      </div>
      <p className="text-xs text-zinc-500 leading-relaxed">{explanation}</p>
    </div>
  );
}
