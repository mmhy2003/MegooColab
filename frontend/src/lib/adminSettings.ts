"use client";

import { useQuery, type QueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
import type { AdminSettings } from "@/lib/types";

export type SettingsPatch = {
  name?: string;
  smtp?: { host: string | null; port: number | null; user: string | null; from: string | null; tls: boolean; password: string | null };
  dreaming?: { enabled: boolean; hour_utc: number | null };
  project_defaults?: AdminSettings["project_defaults"];
};

export function useAdminSettings() {
  return useQuery({ queryKey: qk.adminSettings(), queryFn: () => api<AdminSettings>("/api/admin/settings") });
}

/** One tab's save. The server needs the name and the email settings every time, so those come from what is saved
 * (the password left out, which keeps it); dreaming and the project defaults are only sent by the tab that edits them. */
export async function saveAdminSettings(client: QueryClient, saved: AdminSettings, patch: SettingsPatch): Promise<void> {
  const s = saved.smtp;
  await api("/api/admin/settings", {
    method: "PUT",
    json: {
      name: saved.name,
      smtp: { host: s.host ?? null, port: s.port ?? null, user: s.user ?? null, from: s.from ?? null, tls: s.tls ?? true, password: null },
      ...patch,
    },
  });
  await client.invalidateQueries({ queryKey: qk.adminSettings() });
  await client.invalidateQueries({ queryKey: qk.org() });
}
