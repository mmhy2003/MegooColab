"use client";

import { Blocks, BookOpen, BookOpenText, Bot, Brain, BrainCircuit, FolderKanban, GitPullRequest, LayoutDashboard, MessageCircle, MessagesSquare, ScrollText, Settings2, Users, UsersRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Brand } from "@/components/Brand";
import { useChatsWaiting } from "@/lib/chats";
import { useDashboardCount } from "@/lib/dashboard";
import { useHubSummary } from "@/lib/hub";
import type { User } from "@/lib/types";

type Item = { href: string; label: string; icon: typeof FolderKanban };

/** Hidden while the collapsed rail is closed, shown as it slides open (hover, or tabbing in with the keyboard). Still read out. */
export const LABEL_HIDDEN = "opacity-0 transition-opacity group-hover/side:opacity-100 group-has-[:focus-visible]/side:opacity-100";

const DASHBOARD: Item = { href: "/", label: "Dashboard", icon: LayoutDashboard };

const CHATS: Item = { href: "/chats", label: "Chats", icon: MessageCircle };

const HUB: Item = { href: "/hub", label: "Tool Hub", icon: Blocks };

const MAIN: Item[] = [
  { href: "/projects", label: "Projects", icon: FolderKanban },
  CHATS,
  { href: "/teams", label: "Teams", icon: UsersRound },
  { href: "/kb", label: "Knowledge Base", icon: BookOpen },
  { href: "/memory", label: "Memory", icon: Brain },
  HUB,
  { href: "/questions", label: "Questions", icon: MessagesSquare },
];

const ADMIN: Item[] = [
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/agents", label: "Agents", icon: Bot },
  { href: "/admin/hub", label: "Tool Hub", icon: Blocks },
  { href: "/admin/settings", label: "Settings", icon: Settings2 },
  { href: "/admin/methodology", label: "Methodology", icon: BookOpenText },
  { href: "/admin/ai", label: "AI", icon: BrainCircuit },
  { href: "/admin/git", label: "Git", icon: GitPullRequest },
  { href: "/admin/audit", label: "Audit log", icon: ScrollText },
];

function NavLink({
  item,
  onNavigate,
  collapsed,
  badge = 0,
  badgeLabel = "need you",
  mark,
}: {
  item: Item;
  onNavigate?: () => void;
  collapsed?: boolean;
  badge?: number;
  badgeLabel?: string;
  /** a dot on the icon, named for screen readers */
  mark?: string;
}) {
  const pathname = usePathname();
  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={`relative flex items-center gap-2 rounded px-3 py-2 text-sm whitespace-nowrap no-underline ${
        active ? "bg-cyan/10 font-semibold text-cyan-ink" : "text-muted-foreground hover:bg-surface hover:text-fg"
      }`}
    >
      {/* the active item's bar, on the sidebar's left edge (the nav's p-2), the collapsed rail's too */}
      {active && <span data-accent aria-hidden className="absolute inset-y-1.5 -left-2 w-[3px] rounded-r bg-cyan shadow-[var(--glow-cyan)]" />}
      <span className="relative shrink-0">
        <Icon size={16} aria-hidden />
        {/* on the collapsed rail the count sits on the icon's corner, like the bell's */}
        {badge > 0 && collapsed && <CountBadge n={badge} label={badgeLabel} className="absolute -top-2 -right-2" />}
        {mark && <span aria-label={mark} className="absolute -top-1 -right-1 size-2 rounded-full bg-amber" />}
      </span>
      <span className={collapsed ? LABEL_HIDDEN : ""}>{item.label}</span>
      {badge > 0 && !collapsed && <CountBadge n={badge} label={badgeLabel} className="ml-auto" />}
    </Link>
  );
}

function CountBadge({ n, label, className }: { n: number; label: string; className: string }) {
  return (
    <span aria-label={`${n} ${label}`} className={`min-w-4 rounded-full bg-pink px-1 text-center text-[10px] leading-4 text-on-accent ${className}`}>
      {n > 99 ? "99+" : n}
    </span>
  );
}

/** The Dashboard entry, with the "Need you" count (hidden at zero). */
function DashboardLink({ onNavigate, collapsed }: { onNavigate?: () => void; collapsed?: boolean }) {
  const count = useDashboardCount().data?.needs_you ?? 0;
  return <NavLink item={DASHBOARD} onNavigate={onNavigate} collapsed={collapsed} badge={count} />;
}

/** Chats, with how many wait on the viewer (a question, an approval, an escalation). */
function ChatsLink({ onNavigate, collapsed }: { onNavigate?: () => void; collapsed?: boolean }) {
  const count = useChatsWaiting().data?.waiting ?? 0;
  return <NavLink item={CHATS} onNavigate={onNavigate} collapsed={collapsed} badge={count} badgeLabel="waiting on you" />;
}

/** The Tool Hub, marked when one of the viewer's machines doesn't match their library. */
function HubLink({ onNavigate, collapsed }: { onNavigate?: () => void; collapsed?: boolean }) {
  const outOfStep = useHubSummary().data?.out_of_step ?? false;
  return <NavLink item={HUB} onNavigate={onNavigate} collapsed={collapsed} mark={outOfStep ? "Tool Hub needs a push" : undefined} />;
}

export function Sidebar({ user, onNavigate, collapsed }: { user: User; onNavigate?: () => void; collapsed?: boolean }) {
  return (
    // p-2 and the links' px-3 put the icons in the middle of the collapsed rail (w-14), so they stay put as it opens
    <nav aria-label="Main" className="flex h-full flex-col gap-1 p-2">
      {/* text-base and px-2: the logo and the name fit the 14rem sidebar on one line */}
      <Link href="/" className="mb-4 px-2 py-2 text-base no-underline" onClick={onNavigate}>
        <Brand logoSize={28} nameClassName={collapsed ? LABEL_HIDDEN : ""} />
      </Link>
      <DashboardLink onNavigate={onNavigate} collapsed={collapsed} />
      {MAIN.map((item) =>
        item === CHATS ? (
          <ChatsLink key={item.href} onNavigate={onNavigate} collapsed={collapsed} />
        ) : item === HUB ? (
          <HubLink key={item.href} onNavigate={onNavigate} collapsed={collapsed} />
        ) : (
          <NavLink key={item.href} item={item} onNavigate={onNavigate} collapsed={collapsed} />
        ),
      )}
      {user.role === "admin" && (
        <>
          <p className={`mt-6 mb-1 px-3 text-[11px] tracking-widest whitespace-nowrap text-muted-foreground uppercase ${collapsed ? LABEL_HIDDEN : ""}`}>Admin</p>
          {ADMIN.map((item) => (
            <NavLink key={item.href} item={item} onNavigate={onNavigate} collapsed={collapsed} />
          ))}
        </>
      )}
    </nav>
  );
}
