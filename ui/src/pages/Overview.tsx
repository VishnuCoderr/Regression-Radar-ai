// src/pages/Overview.tsx — Dashboard / Overview page
import { useEffect, useState } from "react";import { Link } from "react-router-dom";
import { Zap, GitPullRequest, TrendingUp, ChevronRight } from "lucide-react";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { RiskBadge } from "../components/ui/Badge";
import { useAnalysisStore } from "../store/analysisStore";
import { checkHealth } from "../api/client";
import type { AnalysisRecord } from "../types/api";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";

function riskColor(cat: string) {
  return { low: "#22c55e", medium: "#f59e0b", high: "#ef4444", critical: "#dc2626" }[cat] ?? "#555";
}

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
}) {
  return (
    <Card className="p-5">
      <div className="text-xs text-zinc-500 uppercase tracking-wider mb-1">{label}</div>
      <div className="text-3xl font-bold text-white mb-0.5" style={accent ? { color: accent } : {}}>
        {value}
      </div>
      {sub && <div className="text-xs text-zinc-600">{sub}</div>}
    </Card>
  );
}

export function Overview() {
  const { records } = useAnalysisStore();
  const [apiVersion, setApiVersion] = useState<string | null>(null);

  useEffect(() => {
    checkHealth()
      .then((h) => setApiVersion(h.version))
      .catch(() => setApiVersion(null));
  }, []);

  const highRisk = records.filter(
    (r) => r.result.risk_category === "high" || r.result.risk_category === "critical",
  );
  const avgScore =
    records.length > 0
      ? (records.reduce((a, r) => a + r.result.overall_score, 0) / records.length).toFixed(1)
      : "—";

  // Distribution for chart
  const dist = ["low", "medium", "high", "critical"].map((cat) => ({
    name: cat.charAt(0).toUpperCase() + cat.slice(1),
    count: records.filter((r) => r.result.risk_category === cat).length,
    color: riskColor(cat),
  }));

  return (
    <div className="p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-white mb-1">Overview</h1>
        <p className="text-zinc-500 text-sm">
          PR risk intelligence across your repositories.{" "}
          {apiVersion && (
            <span className="text-zinc-600">API v{apiVersion}</span>
          )}
        </p>
      </div>

      {records.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <StatCard label="Analyses" value={records.length} sub="this session" />
            <StatCard
              label="High Risk"
              value={highRisk.length}
              sub="High + Critical"
              accent={highRisk.length > 0 ? "#ef4444" : undefined}
            />
            <StatCard label="Avg Score" value={avgScore} sub="risk-prioritization" />
            <StatCard
              label="Last Score"
              value={records[0] ? Math.round(records[0].result.overall_score) : "—"}
              sub={records[0]?.result.risk_category ?? ""}
              accent={records[0] ? riskColor(records[0].result.risk_category) : undefined}
            />
          </div>

          {/* Two-column layout */}
          <div className="grid lg:grid-cols-5 gap-6">
            {/* Recent analyses */}
            <Card className="lg:col-span-3">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-white">Recent Analyses</h2>
                  <Link
                    to="/history"
                    className="text-xs text-blue-500 hover:text-blue-400 flex items-center gap-1"
                  >
                    View all <ChevronRight className="w-3 h-3" />
                  </Link>
                </div>
              </CardHeader>
              <div className="divide-y divide-[#2a2a38]">
                {records.slice(0, 8).map((rec) => (
                  <RecentRow key={rec.id} rec={rec} />
                ))}
              </div>
            </Card>

            {/* Distribution chart */}
            <Card className="lg:col-span-2">
              <CardHeader>
                <h2 className="text-sm font-semibold text-white">Risk Distribution</h2>
              </CardHeader>
              <CardBody className="pt-2">
                <ResponsiveContainer width="100%" height={160}>
                  <BarChart data={dist} barCategoryGap="30%">
                    <XAxis
                      dataKey="name"
                      tick={{ fontSize: 11, fill: "#666" }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis hide />
                    <Tooltip
                      contentStyle={{
                        background: "#18181f",
                        border: "1px solid #2a2a38",
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                      labelStyle={{ color: "#aaa" }}
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {dist.map((d, i) => (
                        <Cell key={i} fill={d.color} fillOpacity={0.85} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>

                {/* Legend */}
                <div className="space-y-2 mt-4">
                  {dist.map((d) => (
                    <div key={d.name} className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span
                          className="w-2 h-2 rounded-sm"
                          style={{ background: d.color, opacity: 0.85 }}
                        />
                        <span className="text-zinc-400">{d.name}</span>
                      </div>
                      <span className="text-zinc-600 font-mono">{d.count}</span>
                    </div>
                  ))}
                </div>
              </CardBody>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function RecentRow({ rec }: { rec: AnalysisRecord }) {
  const name = rec.repo_path.split(/[\\/]/).pop() ?? rec.repo_path;
  const date = new Date(rec.timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <Link
      to="/history"
      className="flex items-center gap-4 px-5 py-3 hover:bg-white/[0.02] transition-colors"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <GitPullRequest className="w-3.5 h-3.5 text-zinc-600 flex-shrink-0" />
          <span className="text-sm text-zinc-200 truncate font-medium">{name}</span>
        </div>
        <span className="text-xs text-zinc-600">
          {rec.base_ref} → {rec.head_ref}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-sm font-bold font-mono text-white">
          {Math.round(rec.result.overall_score)}
        </span>
        <RiskBadge category={rec.result.risk_category} />
        <span className="text-xs text-zinc-700 w-12 text-right">{date}</span>
      </div>
    </Link>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="w-12 h-12 rounded-xl bg-blue-600/10 border border-blue-600/20 flex items-center justify-center mb-4">
        <TrendingUp className="w-6 h-6 text-blue-500" />
      </div>
      <h2 className="text-lg font-semibold text-white mb-2">No analyses yet</h2>
      <p className="text-zinc-500 text-sm max-w-xs mb-6">
        Run your first PR risk analysis to see risk scoring, signal breakdown and reviewer suggestions.
      </p>
      <Link
        to="/analyze"
        className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors"
      >
        <Zap className="w-4 h-4" />
        Analyze a PR
      </Link>
    </div>
  );
}
