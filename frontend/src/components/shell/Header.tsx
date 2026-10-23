"use client";

import { Bot, KeyRound, LogOut, Menu, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { Avatar } from "@/components/ui/Avatar";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

function crumbs(pathname: string): { href: string; label: string }[] {
  const parts = pathname.split("/").filter(Boolean);
  return parts.map((p, i) => ({ href: `/${parts.slice(0, i + 1).join("/")}`, label: decodeURIComponent(p) }));
}

export function Header({ user, onMenu }: { user: User; onMenu: () => void }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  return (
    <header className="flex h-12 items-center gap-2 border-b border-line bg-surface-2/80 px-3 backdrop-blur">
      <button type="button" className="icon-btn md:hidden" aria-label="Open menu" onClick={onMenu}>
        <Menu size={18} aria-hidden />
      </button>
      <nav aria-label="Breadcrumb" className="min-w-0 flex-1 truncate text-xs text-muted">
        {crumbs(pathname).map((c, i, all) => (
          <span key={c.href}>
            {i > 0 && <span className="mx-1">/</span>}
            {i === all.length - 1 ? (
              <span className="text-fg">{c.label}</span>
            ) : (
              <Link href={c.href} className="text-muted no-underline hover:text-cyan-ink">
                {c.label}
              </Link>
            )}
          </span>
        ))}
      </nav>
      <ThemeToggle />
      <div className="relative">
        <button
          type="button"
          className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-surface"
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <Avatar name={user.name} size={22} />
          <span className="hidden sm:inline">{user.name}</span>
        </button>
        {open && (
          <div role="menu" className="card absolute right-0 z-20 mt-1 w-44 p-1" onMouseLeave={() => setOpen(false)}>
            <Link role="menuitem" href="/settings/profile" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded px-3 py-2 text-sm text-fg no-underline hover:bg-surface-2">
              <UserRound size={14} aria-hidden /> Profile
            </Link>
            <Link role="menuitem" href="/settings/tokens" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded px-3 py-2 text-sm text-fg no-underline hover:bg-surface-2">
              <KeyRound size={14} aria-hidden /> Access tokens
            </Link>
            <Link role="menuitem" href="/settings/agents" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded px-3 py-2 text-sm text-fg no-underline hover:bg-surface-2">
              <Bot size={14} aria-hidden /> My agents
            </Link>
            <button
              role="menuitem"
              type="button"
              className="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm hover:bg-surface-2"
              onClick={async () => {
                await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
                window.location.assign("/login");
              }}
            >
              <LogOut size={14} aria-hidden /> Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
