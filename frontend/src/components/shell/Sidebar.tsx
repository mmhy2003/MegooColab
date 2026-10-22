"use client";

import { FolderKanban, ScrollText, Settings2, Users, UsersRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Brand } from "@/components/Brand";
import type { User } from "@/lib/types";

type Item = { href: string; label: string; icon: typeof FolderKanban };

const MAIN: Item[] = [
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/teams", label: "Teams", icon: UsersRound },
];

const ADMIN: Item[] = [
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/settings", label: "Settings", icon: Settings2 },
  { href: "/admin/audit", label: "Audit log", icon: ScrollText },
];

function NavLink({ item, onNavigate }: { item: Item; onNavigate?: () => void }) {
  const pathname = usePathname();
  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-2 rounded px-3 py-2 text-sm no-underline ${
        active ? "bg-surface-2 text-cyan-ink glow-cyan" : "text-muted hover:bg-surface-2 hover:text-fg"
      }`}
    >
      <Icon size={16} aria-hidden />
      {item.label}
    </Link>
  );
}

export function Sidebar({ user, onNavigate }: { user: User; onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex h-full flex-col gap-1 p-3">
      <Link href="/projects" className="mb-4 px-3 py-2 text-lg no-underline" onClick={onNavigate}>
        <Brand />
      </Link>
      {MAIN.map((item) => (
        <NavLink key={item.href} item={item} onNavigate={onNavigate} />
      ))}
      {user.role === "admin" && (
        <>
          <p className="mt-6 mb-1 px-3 text-[11px] tracking-widest text-muted uppercase">Admin</p>
          {ADMIN.map((item) => (
            <NavLink key={item.href} item={item} onNavigate={onNavigate} />
          ))}
        </>
      )}
    </nav>
  );
}
