"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type Notification = S["NotificationOut"];
export type NotificationPref = S["NotificationPrefIO"];
export type NotificationKind = NotificationPref["kind"];

export const PAGE = 50;

export const KIND_LABELS: Record<NotificationKind, string> = {
  needs_you: "A task or answer needs me",
  assigned: "Assigned to me",
  mentioned: "Mentioned in a comment",
  agent_offline: "My agent went offline mid-task",
  question_waiting: "A question waits for an answer",
};

/** Every notifications query starts with "notifications", so one invalidation (notification.* events) refreshes
 * the bell, the list and the preferences. */
export const notificationKeys = {
  all: ["notifications"] as const,
  count: () => ["notifications", "count"] as const,
  list: (unread: boolean) => ["notifications", "list", unread] as const,
  prefs: () => ["notifications", "prefs"] as const,
};

export function useUnreadCount() {
  return useQuery({
    queryKey: notificationKeys.count(),
    queryFn: () => api<{ count: number }>("/api/notifications/unread-count"),
  });
}

/** Newest first, 50 per page; the next page starts before the last row (its time, then its id). */
export function useNotifications(unread = false, enabled = true) {
  return useInfiniteQuery({
    queryKey: notificationKeys.list(unread),
    enabled,
    initialPageParam: null as Notification | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ unread: String(unread) });
      if (pageParam) {
        params.set("before", pageParam.created_at);
        params.set("before_id", pageParam.id);
      }
      return api<Notification[]>(`/api/notifications?${params}`);
    },
    getNextPageParam: (last) => (last.length === PAGE ? last[last.length - 1] : undefined),
  });
}

export function useMarkRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api(`/api/notifications/${id}/read`, { method: "POST" }),
    onSettled: () => client.invalidateQueries({ queryKey: notificationKeys.all }),
  });
}

export function useMarkAllRead() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api("/api/notifications/read-all", { method: "POST" }),
    onSettled: () => client.invalidateQueries({ queryKey: notificationKeys.all }),
  });
}

export function useNotificationPrefs() {
  return useQuery({
    queryKey: notificationKeys.prefs(),
    queryFn: () => api<NotificationPref[]>("/api/me/notification-preferences"),
  });
}

export function useSavePref() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (pref: NotificationPref) =>
      api<NotificationPref[]>("/api/me/notification-preferences", { method: "PUT", json: [pref] }),
    onSuccess: (prefs) => client.setQueryData(notificationKeys.prefs(), prefs),
  });
}

// mirrors app/notifications/service.py MENTION
export const MENTION_RE = /@\[([^\]\n]{1,200})\]\(user:([0-9a-f-]{36})\)/g;

/** The token the comment picker inserts; rendered as `@Name`. Brackets in a name would end the token early. */
export function mentionToken(user: { id: string; name: string }): string {
  return `@[${user.name.replace(/[[\]\n]/g, " ").slice(0, 200)}](user:${user.id})`;
}
