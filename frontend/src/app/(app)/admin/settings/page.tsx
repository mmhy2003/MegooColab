"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { SearchAdmin } from "@/components/admin/SearchAdmin";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { AdminSettings } from "@/lib/types";
import { FINISHING_LABEL, type FinishingOption } from "@/lib/workflow";

type Defaults = AdminSettings["project_defaults"];
type Form = {
  name: string; host: string; port: string; user: string; from: string; tls: boolean; password: string;
  dreamEnabled: boolean; dreamHour: string; defaults: Defaults;
};

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
    dreamEnabled: settings.dreaming.enabled,
    dreamHour: settings.dreaming.hour_utc == null ? "" : String(settings.dreaming.hour_utc),
    defaults: settings.project_defaults,
  };
}

export default function AdminSettingsPage() {
  const settings = useQuery({ queryKey: qk.adminSettings(), queryFn: () => api<AdminSettings>("/api/admin/settings") });
  if (!settings.data) return <p className="text-sm text-muted">Loading…</p>;
  return (
    <div className="max-w-xl space-y-4">
      <SettingsForm settings={settings.data} />
      <SearchAdmin />
    </div>
  );
}

function SettingsForm({ settings }: { settings: AdminSettings }) {
  const client = useQueryClient();
  const [form, setForm] = useState<Form>(() => toForm(settings));
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [testTo, setTestTo] = useState("");
  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });
  const setDefault = (patch: Partial<Defaults>) => set({ defaults: { ...form.defaults, ...patch } });

  return (
    <div className="max-w-xl">
      <PageHeader title="Settings" subtitle="Organization name, outgoing email, nightly dreaming and what new projects start with." />
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
                dreaming: { enabled: form.dreamEnabled, hour_utc: form.dreamHour === "" ? null : Number(form.dreamHour) },
                project_defaults: form.defaults,
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
        <fieldset className="space-y-3 border-t border-line pt-4">
          <legend className="pr-2 text-xs tracking-wider text-muted uppercase">Dreaming</legend>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.dreamEnabled} onChange={(e) => set({ dreamEnabled: e.target.checked })} /> Run dreaming every night
          </label>
          <Input
            label="Dreaming hour (UTC)"
            type="number"
            min={0}
            max={23}
            placeholder="The server's setting"
            value={form.dreamHour}
            onChange={(e) => set({ dreamHour: e.target.value })}
          />
        </fieldset>
        <fieldset className="space-y-3 border-t border-line pt-4">
          <legend className="pr-2 text-xs tracking-wider text-muted uppercase">New projects</legend>
          <Select
            label="Default finishing option"
            value={form.defaults.finishing_option}
            onChange={(e) => setDefault({ finishing_option: e.target.value as FinishingOption })}
          >
            {(Object.keys(FINISHING_LABEL) as FinishingOption[]).map((o) => (
              <option key={o} value={o}>{FINISHING_LABEL[o]}</option>
            ))}
          </Select>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.defaults.require_human_code_review} onChange={(e) => setDefault({ require_human_code_review: e.target.checked })} /> Require a human code review
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.defaults.sprints_enabled} onChange={(e) => setDefault({ sprints_enabled: e.target.checked })} /> Sprints
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.defaults.commit_docs_to_repo} onChange={(e) => setDefault({ commit_docs_to_repo: e.target.checked })} /> Commit design and plan documents to the repository
          </label>
          <p className="text-xs text-muted">Existing projects keep their own settings.</p>
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
