"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Suspense, useState } from "react";

import { RateLimitsAdmin } from "@/components/admin/RateLimitsAdmin";
import { SearchAdmin } from "@/components/admin/SearchAdmin";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { TabPanel, Tabs, useTabParam } from "@/components/ui/Tabs";
import { api } from "@/lib/api";
import { saveAdminSettings, type SettingsPatch, useAdminSettings } from "@/lib/adminSettings";
import { errorMessage } from "@/lib/errors";
import type { AdminSettings } from "@/lib/types";
import { FINISHING_LABEL, type FinishingOption } from "@/lib/workflow";

const TABS = [
  { id: "general", label: "General" },
  { id: "email", label: "Email" },
  { id: "new-projects", label: "New projects" },
  { id: "search", label: "Search" },
  { id: "rate-limits", label: "Rate limits" },
] as const;
type TabId = (typeof TABS)[number]["id"];

type Status = { ok: boolean; text: string } | null;

function StatusLine({ status }: { status: Status }) {
  return status && <p role="status" className={`text-sm ${status.ok ? "text-green-ink" : "text-pink"}`}>{status.text}</p>;
}

/** A tab's form: saves only what the tab edits (see saveAdminSettings). */
function useSave(settings: AdminSettings) {
  const client = useQueryClient();
  const [status, setStatus] = useState<Status>(null);
  const save = async (patch: SettingsPatch, after?: () => void) => {
    try {
      await saveAdminSettings(client, settings, patch);
      after?.();
      setStatus({ ok: true, text: "Saved." });
    } catch (err) {
      setStatus({ ok: false, text: errorMessage(err) });
    }
  };
  return { status, save };
}

function GeneralForm({ settings }: { settings: AdminSettings }) {
  const [name, setName] = useState(settings.name);
  const { status, save } = useSave(settings);
  return (
    <form
      className="card space-y-4 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void save({ name });
      }}
    >
      <Input label="Organization name" required value={name} onChange={(e) => setName(e.target.value)} />
      <StatusLine status={status} />
      <Button type="submit">Save</Button>
    </form>
  );
}

function EmailForm({ settings }: { settings: AdminSettings }) {
  const s = settings.smtp;
  const [form, setForm] = useState({
    host: s.host ?? "", port: s.port ? String(s.port) : "587", user: s.user ?? "", from: s.from ?? "", tls: s.tls ?? true, password: "",
  });
  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch });
  const { status, save } = useSave(settings);
  const [testTo, setTestTo] = useState("");
  const [testStatus, setTestStatus] = useState<Status>(null);
  return (
    <div className="space-y-4">
      <form
        className="card space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          void save(
            {
              smtp: {
                host: form.host || null,
                port: form.port ? Number(form.port) : null,
                user: form.user || null,
                from: form.from || null,
                tls: form.tls,
                password: form.password || null,
              },
            },
            () => set({ password: "" }),
          );
        }}
      >
        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2"><Input label="Host" value={form.host} onChange={(e) => set({ host: e.target.value })} /></div>
          <Input label="Port" inputMode="numeric" value={form.port} onChange={(e) => set({ port: e.target.value })} />
        </div>
        <Input label="Username" value={form.user} onChange={(e) => set({ user: e.target.value })} />
        <Input
          label={s.password_set ? "Password (leave empty to keep the saved one)" : "Password"}
          type="password"
          autoComplete="new-password"
          value={form.password}
          onChange={(e) => set({ password: e.target.value })}
        />
        <Input label="From address" type="email" value={form.from} onChange={(e) => set({ from: e.target.value })} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={form.tls} onChange={(e) => set({ tls: e.target.checked })} /> Use STARTTLS
        </label>
        <StatusLine status={status} />
        <Button type="submit">Save</Button>
      </form>
      <form
        className="card space-y-3 p-4"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api("/api/admin/settings/test-email", { method: "POST", json: { to: testTo } });
            setTestStatus({ ok: true, text: `Test email sent to ${testTo}.` });
          } catch (err) {
            setTestStatus({ ok: false, text: `Test failed: ${errorMessage(err)}` });
          }
        }}
      >
        <div className="flex items-end gap-2">
          <div className="flex-1"><Input label="Send a test email to" type="email" required value={testTo} onChange={(e) => setTestTo(e.target.value)} /></div>
          <Button type="submit" variant="ghost">Send test</Button>
        </div>
        <StatusLine status={testStatus} />
      </form>
    </div>
  );
}

function DefaultsForm({ settings }: { settings: AdminSettings }) {
  const [defaults, setDefaults] = useState(settings.project_defaults);
  const set = (patch: Partial<AdminSettings["project_defaults"]>) => setDefaults({ ...defaults, ...patch });
  const { status, save } = useSave(settings);
  return (
    <form
      className="card space-y-3 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        void save({ project_defaults: defaults });
      }}
    >
      <Select
        label="Default finishing option"
        value={defaults.finishing_option}
        onChange={(e) => set({ finishing_option: e.target.value as FinishingOption })}
      >
        {(Object.keys(FINISHING_LABEL) as FinishingOption[]).map((o) => (
          <option key={o} value={o}>{FINISHING_LABEL[o]}</option>
        ))}
      </Select>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={defaults.require_human_code_review} onChange={(e) => set({ require_human_code_review: e.target.checked })} /> Require a human code review
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={defaults.sprints_enabled} onChange={(e) => set({ sprints_enabled: e.target.checked })} /> Sprints
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={defaults.commit_docs_to_repo} onChange={(e) => set({ commit_docs_to_repo: e.target.checked })} /> Commit design and plan documents to the repository
      </label>
      <p className="text-xs text-muted-foreground">Existing projects keep their own settings.</p>
      <StatusLine status={status} />
      <Button type="submit">Save</Button>
    </form>
  );
}

function SettingsTabs() {
  const settings = useAdminSettings();
  const [tab, setTab] = useTabParam<TabId>(TABS.map((t) => t.id));
  return (
    <div className="max-w-xl">
      <PageHeader title="Settings" subtitle="Organization name, outgoing email, what new projects start with, search and rate limits." />
      <Tabs label="Settings sections" tabs={TABS} value={tab} onChange={setTab} />
      {!settings.data ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <>
          <TabPanel id="general" active={tab === "general"}><GeneralForm settings={settings.data} /></TabPanel>
          <TabPanel id="email" active={tab === "email"}><EmailForm settings={settings.data} /></TabPanel>
          <TabPanel id="new-projects" active={tab === "new-projects"}><DefaultsForm settings={settings.data} /></TabPanel>
          <TabPanel id="search" active={tab === "search"}><SearchAdmin /></TabPanel>
          <TabPanel id="rate-limits" active={tab === "rate-limits"}><RateLimitsAdmin /></TabPanel>
        </>
      )}
    </div>
  );
}

export default function AdminSettingsPage() {
  return (
    <Suspense>
      <SettingsTabs />
    </Suspense>
  );
}
