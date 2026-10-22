"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
import type { User } from "@/lib/types";

export function useMe() {
  return useQuery({
    queryKey: qk.me(),
    queryFn: async () => (await api<{ user: User }>("/api/auth/me")).user,
    staleTime: 5 * 60_000,
  });
}

export function canManage(user: User | undefined): boolean {
  return user?.role === "admin" || user?.role === "manager";
}
