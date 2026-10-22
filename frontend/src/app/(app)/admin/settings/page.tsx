"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { AdminSettings } from "@/lib/types";

type Form = { name: string; host: string; port: string; user: string; from: string; tls: boolean; password: string };

function toForm(settings: AdminSettings): Form {
  const s = settings.smtp;
  return {
    name: settings.name,
    host: s.host ?? "",
    port: s.port ? String(s.port) : "587",
    user: s.user ?? "",
    from: s.from ?? "",
    tls: s.tls ?? true,
    password: "",
  };
}

export default function AdminSettingsPage() {
  const settings = useQuery({ queryKey: qk.adminSettings(), queryFn: () => api<AdminSettings>("/api/admin/settings") });
  if (!settings.data) return <p className="text-sm text-muted">Loading…</p>;
  return <SettingsForm settings={settings.data} />;
}

function SettingsForm({ settings }: { settings: AdminSettings }) {
  const client = useQueryClient();
  const [form, setForm] = useState<Form>(() => toForm(settings));
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [testTo, setTestTo] = useState("");
  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });

  return (
    <div className="max-w-xl">
      <PageHeader title="Settings" subtitle="Organization name and outgoing email." />
      <form
        className="card space-y-4 p-4"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/api/admin/settings", {
              method: "PUT",
              json: {
                name: form.name,
                smtp: {
                  host: form.host || null,
                  port: form.port ? Number(form.port) : null,
                  user: form.user || null,
                  from: form.from || null,
                  tls: form.tls,
                  password: form.password || null,
                },
              },
            });
            set({ password: "" });
            setStatus({ ok: true, text: "Saved." });
            await client.invalidateQueries({ queryKey: qk.adminSettings() });
            await client.invalidateQueries({ queryKey: qk.org() });
          } catch (err) {
            setStatus({ ok: false, text: errorMessage(err) });
          }
        }}
      >
        <Input label="Organization name" required value={form.name} onChange={(e) => set({ name: e.target.value })} />
        <fieldset className="space-y-3 border-t border-line pt-4">
          <legend className="pr-2 text-xs tracking-wider text-muted uppercase">Email (SMTP)</legend>
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2"><Input label="Host" value={form.host} onChange={(e) => set({ host: e.target.value })} /></div>
            <Input label="Port" inputMode="numeric" value={form.port} onChange={(e) => set({ port: e.target.value })} />
          </div>
          <Input label="Username" value={form.user} onChange={(e) => set({ user: e.target.value })} />
          <Input
            label={settings.smtp.password_set ? "Password (leave empty to keep the saved one)" : "Password"}
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => set({ password: e.target.value })}
          />
          <Input label="From address" type="email" value={form.from} onChange={(e) => set({ from: e.target.value })} />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.tls} onChange={(e) => set({ tls: e.target.checked })} /> Use STARTTLS
          </label>
        </fieldset>
        {status && <p role="status" className={`text-sm ${status.ok ? "text-green-ink" : "text-pink"}`}>{status.text}</p>}
        <Button type="submit">Save</Button>
      </form>
      <form
        className="card mt-4 flex items-end gap-2 p-4"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/api/admin/settings/test-email", { method: "POST", json: { to: testTo } });
            setStatus({ ok: true, text: `Test email sent to ${testTo}.` });
          } catch (err) {
            setStatus({ ok: false, text: `Test failed: ${errorMessage(err)}` });
          }
        }}
      >
        <div className="flex-1"><Input label="Send a test email to" type="email" required value={testTo} onChange={(e) => setTestTo(e.target.value)} /></div>
        <Button type="submit" variant="ghost">Send test</Button>
      </form>
    </div>
  );
}
