// src/components/layout/AppShell.tsx
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";

export function AppShell() {
  return (
    <div className="min-h-screen bg-[#0a0a0f] flex">
      <Sidebar />
      <main className="flex-1 ml-56 min-h-screen">
        <Outlet />
      </main>
    </div>
  );
}
