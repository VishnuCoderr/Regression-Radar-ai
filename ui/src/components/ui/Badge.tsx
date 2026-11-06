// src/components/ui/Badge.tsx
import type { RiskCategory } from "../../types/api";

const styles: Record<RiskCategory | "unavailable", string> = {
  low: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/25",
  medium: "bg-amber-500/15 text-amber-400 border border-amber-500/25",
  high: "bg-red-500/15 text-red-400 border border-red-500/25",
  critical: "bg-red-700/20 text-red-300 border border-red-600/30",
  unavailable: "bg-zinc-700/20 text-zinc-400 border border-zinc-700/30",
};

interface BadgeProps {
  category: RiskCategory | "unavailable";
  className?: string;
}

export function RiskBadge({ category, className = "" }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wide ${styles[category]} ${className}`}
    >
      {category}
    </span>
  );
}

export function Badge({
  children,
  variant = "default",
}: {
  children: React.ReactNode;
  variant?: "default" | "muted";
}) {
  const v =
    variant === "muted"
      ? "bg-white/5 text-zinc-400 border border-white/10"
      : "bg-blue-500/15 text-blue-400 border border-blue-500/25";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${v}`}>
      {children}
    </span>
  );
}
