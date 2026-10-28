"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { NotificationItem } from "@/components/notifications/NotificationList";
import { Backdrop } from "@/components/ui/Backdrop";
import { useMarkAllRead, useNotifications, useUnreadCount } from "@/lib/notifications";

const SHOWN = 10;

/** The header bell: the unread count (hidden at 0), and the latest notifications in a dropdown. */
export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const count = useUnreadCount().data?.count ?? 0;
  const list = useNotifications(false, open);
  const markAll = useMarkAllRead();
  const items = list.data?.pages[0]?.slice(0, SHOWN) ?? [];
  return (
    <div className="relative">
      <button
        type="button"
        className="icon-btn relative"
        aria-label="Notifications"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Bell size={18} aria-hidden />
        {count > 0 && (
          <span className="absolute -top-1 -right-1 min-w-4 rounded-full bg-pink px-1 text-center text-[10px] leading-4 text-on-accent">
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>
      {open && <Backdrop onClose={() => setOpen(false)} />}
      {open && (
        <div role="dialog" aria-label="Notifications" className="card absolute right-0 z-20 mt-1 w-80 p-1">
          <div className="flex items-center justify-between px-3 py-2">
            <span className="text-sm font-semibold">Notifications</span>
            <button
              type="button"
              className="text-xs text-cyan-ink hover:underline disabled:opacity-50"
              disabled={count === 0 || markAll.isPending}
              onClick={() => markAll.mutate()}
            >
              Mark all read
            </button>
          </div>
          {list.isLoading ? (
            <p className="px-3 py-2 text-sm text-muted-foreground">Loading…</p>
          ) : items.length === 0 ? (
            <p className="px-3 py-2 text-sm text-muted-foreground">Nothing new.</p>
          ) : (
            <ul className="max-h-96 divide-y divide-line overflow-y-auto">
              {items.map((n) => (
                <NotificationItem key={n.id} n={n} onOpen={() => setOpen(false)} />
              ))}
            </ul>
          )}
          <Link
            href="/notifications"
            className="block px-3 py-2 text-xs text-cyan-ink no-underline hover:underline"
            onClick={() => setOpen(false)}
          >
            See all
          </Link>
        </div>
      )}
    </div>
  );
}
