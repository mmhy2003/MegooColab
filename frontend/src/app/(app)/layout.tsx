"use client";

import { useState } from "react";

import { Header } from "@/components/shell/Header";
import { Sidebar } from "@/components/shell/Sidebar";
import { useMe } from "@/lib/me";
import { useRealtime } from "@/lib/realtime";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { data: user } = useMe();
  const [menuOpen, setMenuOpen] = useState(false);
  useRealtime();

  if (!user) {
    return <div className="grid min-h-screen place-items-center text-sm text-muted">Loading…</div>;
  }
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-56 shrink-0 border-r border-line bg-surface-2/60 md:block">
        <Sidebar user={user} />
      </aside>
      {menuOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-label="Menu">
          <button type="button" aria-label="Close menu" className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setMenuOpen(false)} />
          <aside className="relative h-full w-64 border-r border-line bg-surface">
            <Sidebar user={user} onNavigate={() => setMenuOpen(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <Header user={user} onMenu={() => setMenuOpen(true)} />
        <main className="min-w-0 flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
