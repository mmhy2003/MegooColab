"use client";

import { Suspense, useState } from "react";

import { NavRecorder } from "@/components/nav/NavRecorder";
import { TabBadge } from "@/components/notifications/TabBadge";
import { AppVersion } from "@/components/shell/AppVersion";
import { DesktopSidebar } from "@/components/shell/DesktopSidebar";
import { Header } from "@/components/shell/Header";
import { Sidebar } from "@/components/shell/Sidebar";
import { useKeepAccountName } from "@/lib/accounts";
import { useChimeUnlock } from "@/lib/beep";
import { useMe } from "@/lib/me";
import { useRealtime } from "@/lib/realtime";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { data: user } = useMe();
  useKeepAccountName(user);
  const [menuOpen, setMenuOpen] = useState(false);
  useRealtime();
  useChimeUnlock();

  if (!user) {
    return <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">Loading…</div>;
  }
  return (
    <div className="flex min-h-screen">
      <Suspense fallback={null}>
        <NavRecorder />
      </Suspense>
      <TabBadge />
      <DesktopSidebar user={user} />
      {menuOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-label="Menu">
          <button type="button" aria-label="Close menu" className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setMenuOpen(false)} />
          <aside className="relative flex h-full w-64 flex-col border-r border-line bg-surface">
            <div className="min-h-0 flex-1">
              <Sidebar user={user} onNavigate={() => setMenuOpen(false)} />
            </div>
            {/* px-5: in line with the menu's icons (the nav's p-2 plus the links' px-3) */}
            <div className="shrink-0 px-5 py-3">
              <AppVersion />
            </div>
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
