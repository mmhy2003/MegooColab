"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { type Notification, useMarkAllRead, useMarkRead, useNotifications } from "@/lib/notifications";

const when = (iso: string) => new Date(iso).toLocaleString();

/** One notification: its title links to where it happened; following the link marks it read. */
export function NotificationItem({ n, onOpen }: { n: Notification; onOpen?: () => void }) {
  const markRead = useMarkRead();
  return (
    <li className={`rounded px-3 py-2 ${n.read_at ? "" : "bg-surface-2"}`}>
      <Link
        href={n.link}
        className="block text-sm text-fg no-underline hover:text-cyan-ink"
        onClick={() => {
          if (!n.read_at) markRead.mutate(n.id);
          onOpen?.();
        }}
      >
        {!n.read_at && <span className="mr-2 inline-block h-2 w-2 rounded-full bg-cyan" aria-hidden />}
        {!n.read_at && <span className="sr-only">Unread: </span>}
        {n.title}
      </Link>
      {n.body && <p className="mt-0.5 truncate text-xs text-muted-foreground">{n.body}</p>}
      <p className="mt-0.5 text-xs text-muted-foreground">{when(n.created_at)}</p>
    </li>
  );
}

export function NotificationList() {
  const [unread, setUnread] = useState(false);
  const list = useNotifications(unread);
  const markAll = useMarkAllRead();
  const items = list.data?.pages.flat() ?? [];
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={unread} onChange={(e) => setUnread(e.target.checked)} />
          Unread only
        </label>
        <Button variant="ghost" onClick={() => markAll.mutate()} disabled={markAll.isPending}>
          Mark all read
        </Button>
      </div>
      {list.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No notifications yet.</p>
      ) : (
        <ul className="card divide-y divide-line p-1">
          {items.map((n) => (
            <NotificationItem key={n.id} n={n} />
          ))}
        </ul>
      )}
      {list.hasNextPage && (
        <Button variant="ghost" onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>
          Load more
        </Button>
      )}
    </div>
  );
}
