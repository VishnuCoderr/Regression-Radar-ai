// src/components/ui/ScoreGauge.tsx — Circular risk score dial
import { type RiskCategory } from "../../types/api";

const riskColor: Record<RiskCategory, string> = {
  low: "#22c55e",
  medium: "#f59e0b",
  high: "#ef4444",
  critical: "#dc2626",
};

interface ScoreGaugeProps {
  score: number;
  category: RiskCategory;
  size?: number;
}

export function ScoreGauge({ score, category, size = 140 }: ScoreGaugeProps) {
  const r = (size - 20) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  // 270° arc (from 135° to 405°) for the gauge track
  const arcFraction = 0.75;
  const arcLen = circumference * arcFraction;
  const fillLen = (score / 100) * arcLen;
  const gap = circumference - arcLen;
  const color = riskColor[category];

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(135deg)" }}>
        {/* Track */}
        <circle
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke="#2a2a38"
          strokeWidth={8}
          strokeDasharray={`${arcLen} ${gap + circumference - arcLen}`}
          strokeLinecap="round"
        />
        {/* Fill */}
        <circle
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke={color}
          strokeWidth={8}
          strokeDasharray={`${fillLen} ${circumference - fillLen}`}
          strokeLinecap="round"
          style={{ transition: "stroke-dasharray 0.6s cubic-bezier(.4,0,.2,1)" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-3xl font-bold text-white leading-none" style={{ color }}>{Math.round(score)}</span>
        <span className="text-xs text-zinc-500 mt-0.5 uppercase tracking-widest">/ 100</span>
      </div>
    </div>
  );
}
