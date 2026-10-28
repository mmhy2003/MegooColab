"use client";

import { BookOpen, BookOpenText, Bot, Brain, BrainCircuit, FolderKanban, GitPullRequest, MessagesSquare, ScrollText, Settings2, Users, UsersRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Brand } from "@/components/Brand";
import type { User } from "@/lib/types";

type Item = { href: string; label: string; icon: typeof FolderKanban };

/** Hidden while the collapsed rail is closed, shown as it slides open (hover, or tabbing in with the keyboard). Still read out. */
export const LABEL_HIDDEN = "opacity-0 transition-opacity group-hover/side:opacity-100 group-has-[:focus-visible]/side:opacity-100";

const MAIN: Item[] = [
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/teams", label: "Teams", icon: UsersRound },
  { href: "/kb", label: "Knowledge Base", icon: BookOpen },
  { href: "/memory", label: "Memory", icon: Brain },
  { href: "/questions", label: "Questions", icon: MessagesSquare },
];

const ADMIN: Item[] = [
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/agents", label: "Agents", icon: Bot },
  { href: "/admin/settings", label: "Settings", icon: Settings2 },
  { href: "/admin/methodology", label: "Methodology", icon: BookOpenText },
  { href: "/admin/ai", label: "AI", icon: BrainCircuit },
  { href: "/admin/git", label: "Git", icon: GitPullRequest },
  { href: "/admin/audit", label: "Audit log", icon: ScrollText },
];

function NavLink({ item, onNavigate, collapsed }: { item: Item; onNavigate?: () => void; collapsed?: boolean }) {
  const pathname = usePathname();
  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-2 rounded px-3 py-2 text-sm whitespace-nowrap no-underline ${
        active ? "bg-surface-2 text-cyan-ink glow-cyan" : "text-muted hover:bg-surface-2 hover:text-fg"
      }`}
    >
      <Icon size={16} aria-hidden className="shrink-0" />
      <span className={collapsed ? LABEL_HIDDEN : ""}>{item.label}</span>
    </Link>
  );
}

export function Sidebar({ user, onNavigate, collapsed }: { user: User; onNavigate?: () => void; collapsed?: boolean }) {
  return (
    // p-2 and the links' px-3 put the icons in the middle of the collapsed rail (w-14), so they stay put as it opens
    <nav aria-label="Main" className="flex h-full flex-col gap-1 p-2">
      {/* text-base and px-2: the logo and the name fit the 14rem sidebar on one line */}
      <Link href="/projects" className="mb-4 px-2 py-2 text-base no-underline" onClick={onNavigate}>
        <Brand logoSize={28} nameClassName={collapsed ? LABEL_HIDDEN : ""} />
      </Link>
      {MAIN.map((item) => (
        <NavLink key={item.href} item={item} onNavigate={onNavigate} collapsed={collapsed} />
      ))}
      {user.role === "admin" && (
        <>
          <p className={`mt-6 mb-1 px-3 text-[11px] tracking-widest whitespace-nowrap text-muted uppercase ${collapsed ? LABEL_HIDDEN : ""}`}>Admin</p>
          {ADMIN.map((item) => (
            <NavLink key={item.href} item={item} onNavigate={onNavigate} collapsed={collapsed} />
          ))}
        </>
      )}
    </nav>
  );
}
