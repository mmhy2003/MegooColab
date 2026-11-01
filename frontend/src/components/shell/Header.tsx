"use client";

import { Bell, Bot, KeyRound, LogOut, Menu, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { NotificationBell } from "@/components/notifications/NotificationBell";
import { SearchLauncher } from "@/components/search/SearchBox";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/shadcn/dropdown-menu";
import { UpdatePill } from "@/components/shell/UpdatePill";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Avatar } from "@/components/ui/Avatar";
import { Backdrop } from "@/components/ui/Backdrop";
import { api } from "@/lib/api";
import { forgetThisDevice } from "@/lib/push";
import type { User } from "@/lib/types";
import { Hint } from "@/components/ui/Hint";
import { TrailNav } from "@/components/shell/TrailNav";
import { useShownTrail } from "@/lib/trail";

const LINKS = [
  { href: "/settings/profile", label: "Profile", icon: UserRound },
  { href: "/settings/tokens", label: "Access tokens", icon: KeyRound },
  { href: "/settings/agents", label: "My agents", icon: Bot },
  { href: "/settings/notifications", label: "Notifications", icon: Bell },
];

export function Header({ user, onMenu }: { user: User; onMenu: () => void }) {
  const pathname = usePathname();
  const trail = useShownTrail(pathname);
  const [open, setOpen] = useState(false);
  return (
    <header className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b border-line bg-surface-2/80 px-3 backdrop-blur">
      <Hint label="Open menu">
        <button type="button" className="icon-btn md:hidden" aria-label="Open menu" onClick={onMenu}>
          <Menu size={18} aria-hidden />
        </button>
      </Hint>
      <TrailNav crumbs={trail.crumbs} />
      <SearchLauncher />
      <UpdatePill />
      <NotificationBell />
      <ThemeToggle />
      <DropdownMenu open={open} onOpenChange={setOpen} modal={false}>
        <DropdownMenuTrigger asChild>
          <button type="button" className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-surface">
            <Avatar name={user.name} size={22} />
            <span className="sr-only sm:not-sr-only">{user.name}</span>
          </button>
        </DropdownMenuTrigger>
        {/* the page behind is blurred while the menu is open; a click on it closes the menu */}
        {open && <Backdrop onClose={() => setOpen(false)} />}
        <DropdownMenuContent align="end" collisionPadding={8} className="w-44">
          {LINKS.map(({ href, label, icon: Icon }) => (
            <DropdownMenuItem key={href} asChild>
              <Link href={href} className="text-fg no-underline">
                <Icon size={14} aria-hidden /> {label}
              </Link>
            </DropdownMenuItem>
          ))}
          <DropdownMenuItem
            onSelect={async () => {
              await forgetThisDevice().catch(() => undefined); // its push stops before the session ends
              await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
              window.location.assign("/login");
            }}
          >
            <LogOut size={14} aria-hidden /> Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}
