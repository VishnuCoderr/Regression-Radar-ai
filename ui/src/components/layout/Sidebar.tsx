// src/components/layout/Sidebar.tsx
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Clock,
  Zap,
  Activity,
} from "lucide-react";

const nav = [
  { to: "/", icon: LayoutDashboard, label: "Overview" },
  { to: "/analyze", icon: Zap, label: "Analyze PR" },
  { to: "/history", icon: Clock, label: "History" },
];

export function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 h-screen w-56 bg-[#0d0d14] border-r border-[#1e1e28] flex flex-col z-20">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-[#1e1e28]">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0">
            <Activity className="w-4 h-4 text-white" />
          </div>
          <div>
            <div className="text-sm font-semibold text-white leading-tight">Regression Radar</div>
            <div className="text-[10px] text-zinc-600 uppercase tracking-wider">PR Risk Analysis</div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {nav.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }: { isActive: boolean }) =>
              `flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? "bg-blue-600/15 text-blue-400 font-medium"
                  : "text-zinc-500 hover:text-zinc-200 hover:bg-white/5"
              }`
            }
          >
            <Icon className="w-4 h-4 flex-shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Backend status indicator */}
      <div className="px-4 py-3 border-t border-[#1e1e28]">
        <BackendPing />
      </div>
    </aside>
  );
}

function BackendPing() {
  const [ok, setOk] = React.useState<boolean | null>(null);

  React.useEffect(() => {
    fetch("/health")
      .then((r) => r.ok && setOk(true))
      .catch(() => setOk(false));
    const id = setInterval(() => {
      fetch("/health")
        .then((r) => r.ok && setOk(true))
        .catch(() => setOk(false));
    }, 15_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex items-center gap-2 text-xs">
      <span
        className={`w-1.5 h-1.5 rounded-full ${
          ok === null ? "bg-zinc-600 animate-pulse" : ok ? "bg-emerald-500" : "bg-red-500"
        }`}
      />
      <span className={ok === null ? "text-zinc-600" : ok ? "text-zinc-500" : "text-red-500"}>
        {ok === null ? "Connecting…" : ok ? "API connected" : "API offline"}
      </span>
    </div>
  );
}

import React from "react";
