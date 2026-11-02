"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type TelegramBot = S["TelegramBotOut"];
export type MyTelegram = S["MyTelegramOut"];

/** Every Telegram query starts with "telegram", so one invalidation refreshes them all. */
export const telegramKeys = {
  all: ["telegram"] as const,
  admin: () => ["telegram", "admin"] as const,
  mine: () => ["telegram", "mine"] as const,
};

/** The site's bot, for its admins. */
export function useAdminTelegram() {
  return useQuery({ queryKey: telegramKeys.admin(), queryFn: () => api<TelegramBot>("/api/admin/telegram") });
}

/** Whether the site has a bot and this person linked their chat; refetchInterval while waiting for Start. */
export function useMyTelegram(refetchInterval: number | false = false) {
  return useQuery({ queryKey: telegramKeys.mine(), queryFn: () => api<MyTelegram>("/api/me/telegram"), refetchInterval });
}
