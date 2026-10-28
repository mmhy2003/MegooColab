"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { AiJobModel, AiProvider, AiTestResult } from "@/lib/types";

const JOB_TEXT: Record<string, { label: string; help: string }> = {
  embeddings: {
    label: "Embeddings",
    help: "Used for semantic Knowledge Base search. Changing the model re-embeds every document in the background.",
  },
  extraction: {
    label: "Extraction",
    help: "Reads new comments, run summaries, reviews and documents and records short conclusions.",
  },
  dreaming: {
    label: "Dreaming",
    help: "Nightly consolidation: replaces outdated conclusions, deduces and induces new ones, refreshes summary cards.",
  },
  answering: { label: "Answering", help: "Answers questions asked of the memory." },
};

/** Which provider and model each AI job uses (MEM-10). */
export function JobModels() {
  const providers = useQuery({ queryKey: qk.aiProviders(), queryFn: () => api<AiProvider[]>("/api/admin/ai/providers") });
  const jobs = useQuery({ queryKey: qk.aiJobs(), queryFn: () => api<AiJobModel[]>("/api/admin/ai/jobs") });
  return (
    <section className="card p-4">
      <h2 className="mb-1 font-display text-sm font-semibold tracking-wider uppercase">Models per job</h2>
      <p className="mb-3 text-xs text-muted">
        Model names use LiteLLM&apos;s format, for example <code className="font-mono">openai/text-embedding-3-small</code>{" "}
        (the provider&apos;s prefix may be left out).
      </p>
      <div className="space-y-4">
        {(jobs.data ?? []).map((j) => (
          <JobRow key={j.job} job={j} providers={providers.data ?? []} />
        ))}
      </div>
    </section>
  );
}

function JobRow({ job, providers }: { job: AiJobModel; providers: AiProvider[] }) {
  const client = useQueryClient();
  const [providerId, setProviderId] = useState(job.provider_id ?? "");
  const [model, setModel] = useState(job.model);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const text = JOB_TEXT[job.job] ?? { label: job.job, help: "" };
  // when the saved values change (after a save, or someone else's), the fields follow them
  const saved = `${job.provider_id ?? ""}|${job.model}`;
  const [synced, setSynced] = useState(saved);
  if (synced !== saved) {
    setSynced(saved);
    setProviderId(job.provider_id ?? "");
    setModel(job.model);
  }

  return (
    <form
      className="space-y-2 rounded border border-line p-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setStatus(null);
        try {
          await api(`/api/admin/ai/jobs/${job.job}`, {
            method: "PUT",
            json: { provider_id: providerId || null, model: model.trim() },
          });
          setStatus({ ok: true, text: "Saved." });
          await client.invalidateQueries({ queryKey: ["ai"] });
        } catch (err) {
          setStatus({ ok: false, text: errorMessage(err) });
        }
      }}
    >
      <p className="font-semibold">{text.label}</p>
      {text.help && <p className="text-xs text-muted">{text.help}</p>}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2">
        <Select label="Provider" value={providerId} onChange={(e) => setProviderId(e.target.value)}>
          <option value="">Not configured</option>
          {providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
        <Input label="Model" maxLength={200} value={model} onChange={(e) => setModel(e.target.value)} />
      </div>
      {status && (
        <p role="status" className={`text-sm break-words ${status.ok ? "text-green-ink" : "text-pink"}`}>
          {status.text}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit">Save</Button>
        <Button
          variant="ghost"
          onClick={async () => {
            setStatus({ ok: true, text: "Testing…" });
            try {
              const r = await api<AiTestResult>(`/api/admin/ai/jobs/${job.job}/test`, { method: "POST" });
              setStatus(
                r.ok
                  ? { ok: true, text: `Works: ${r.model}` }
                  : { ok: false, text: r.error === "not_configured" ? "Not configured yet." : `Failed: ${r.error}` },
              );
            } catch (err) {
              setStatus({ ok: false, text: errorMessage(err) });
            }
          }}
        >
          Test
        </Button>
      </div>
    </form>
  );
}
