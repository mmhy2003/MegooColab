"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { PROGRAM_LABEL } from "@/lib/agents";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import {
  type AskQuestionOut,
  type QuestionSuggestion,
  type TargetAgent,
  questionKeys,
  useQuestionTargets,
  useTargetAgents,
} from "@/lib/questions";

const PROGRAMS = Object.entries(PROGRAM_LABEL).map(([id, label]) => ({ id, label }));

const BODY_MAX = 4000;
const CONTEXT_MAX = 8000;

const SUGGESTION_KIND: Record<string, string> = { question: "Earlier answer", kb: "Knowledge Base", memory: "Memory" };

const FIELD ="w-full rounded border border-line bg-surface-2 px-3 py-2 text-sm text-fg focus:border-cyan focus:outline-none";

/** Who answers: any free agent, a program's agents, or one agent; and, for a choice, what happens when they're
 * busy or offline. */
function AnsweredBy({
  project,
  agents,
  value,
  onChange,
  ifBusy,
  onIfBusy,
}: {
  project: string;
  agents: TargetAgent[];
  value: string;
  onChange: (v: string) => void;
  ifBusy: "wait" | "another";
  onIfBusy: (v: "wait" | "another") => void;
}) {
  const [kind, picked] = value.split(":");
  const matching = kind === "program" ? agents.filter((a) => a.program === picked) : kind === "agent" ? agents.filter((a) => a.id === picked) : agents;
  const free = matching.filter((a) => a.state === "free").length;
  return (
    <div className="space-y-2">
      <Select label="Answered by" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="any">Any free agent</option>
        <optgroup label="By program">
          {PROGRAMS.map((p) => (
            <option key={p.id} value={`program:${p.id}`}>Any {p.label} agent</option>
          ))}
        </optgroup>
        {agents.length > 0 && (
          <optgroup label="A specific agent">
            {agents.map((a) => (
              <option key={a.id} value={`agent:${a.id}`}>{a.name} · {a.state}</option>
            ))}
          </optgroup>
        )}
      </Select>
      {kind === "program" && (
        <p className="text-xs text-muted-foreground">
          {matching.length} of {project}&apos;s agents · {free} free now
        </p>
      )}
      {kind !== "any" && (
        <fieldset className="space-y-1">
          <legend className="text-xs tracking-wider text-muted-foreground uppercase">If they&apos;re busy or offline</legend>
          {(
            [
              ["wait", "Wait for them", "The question waits until one of them is free."],
              ["another", "Let another agent answer", `Any free agent of ${project} answers instead.`],
            ] as const
          ).map(([id, label, help]) => (
            <label key={id} className={`flex cursor-pointer items-start gap-2 rounded border bg-surface-2 px-3 py-2 text-sm ${ifBusy === id ? "border-cyan" : "border-line"}`}>
              <input type="radio" name="if-busy" className="mt-1 accent-cyan" checked={ifBusy === id} onChange={() => onIfBusy(id)} />
              <span>
                {label}
                <span className="block text-xs text-muted-foreground">{help}</span>
              </span>
            </label>
          ))}
        </fieldset>
      )}
    </div>
  );
}

/** Ask another project (A2A-1): existing answers are offered first (A2A-6), then "Ask anyway". */
export function AskQuestion({ taskKey, onAsked }: { taskKey?: string; onAsked?: (id: string) => void }) {
  const client = useQueryClient();
  const targets = useQuestionTargets();
  const [project, setProject] = useState("");
  // "any", "program:<program>" or "agent:<id>"; and when they're busy or offline
  const [answeredBy, setAnsweredBy] = useState("any");
  const [ifBusy, setIfBusy] = useState<"wait" | "another">("wait");
  const agents = useTargetAgents(project);
  const [body, setBody] = useState("");
  const [context, setContext] = useState("");
  const [suggestions, setSuggestions] = useState<QuestionSuggestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const attempt = async (fn: () => Promise<void>) => {
    setError(null);
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const check = () =>
    attempt(async () => {
      setSuggestions(
        await api<QuestionSuggestion[]>("/api/questions/suggest", {
          method: "POST",
          json: { project_key: project, body: body.trim() },
        }),
      );
    });

  const ask = () =>
    attempt(async () => {
      const [kind, value] = answeredBy.split(":");
      const choice =
        kind === "program" ? { prefer_program: value, if_busy: ifBusy } : kind === "agent" ? { prefer_agent_id: value, if_busy: ifBusy } : {};
      const out = await api<AskQuestionOut>("/api/questions", {
        method: "POST",
        json: { project_key: project, body: body.trim(), context: context.trim(), task_key: taskKey ?? null, ...choice },
      });
      await client.invalidateQueries({ queryKey: questionKeys.all });
      setBody("");
      setContext("");
      setSuggestions(null);
      onAsked?.(out.question.id);
    });

  return (
    <section className="card space-y-3 p-4" aria-label="Ask a project">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void check();
        }}
      >
        <Select
          label="Project"
          required
          value={project}
          onChange={(e) => {
            setProject(e.target.value);
            setAnsweredBy("any");
            setSuggestions(null);
          }}
        >
          <option value="">Choose a project…</option>
          {(targets.data ?? []).map((t) => (
            <option key={t.key} value={t.key}>
              {t.key} — {t.name}
            </option>
          ))}
        </Select>
        {project && (
          <AnsweredBy
            project={project}
            agents={agents.data ?? []}
            value={answeredBy}
            onChange={setAnsweredBy}
            ifBusy={ifBusy}
            onIfBusy={setIfBusy}
          />
        )}
        <div className="flex flex-col gap-1">
          <label htmlFor="q-body" className="text-xs tracking-wider text-muted-foreground uppercase">
            Question
          </label>
          <textarea
            id="q-body"
            required
            rows={3}
            maxLength={BODY_MAX}
            placeholder="What payload does /orders/sync send, and how is it signed?"
            className={FIELD}
            value={body}
            onChange={(e) => {
              setBody(e.target.value);
              setSuggestions(null);
            }}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="q-context" className="text-xs tracking-wider text-muted-foreground uppercase">
            Context (optional)
          </label>
          <textarea
            id="q-context"
            rows={2}
            maxLength={CONTEXT_MAX}
            placeholder="Errors you saw and what you already tried."
            className={FIELD}
            value={context}
            onChange={(e) => setContext(e.target.value)}
          />
        </div>
        {suggestions === null && (
          <Button type="submit" disabled={busy || !project || !body.trim()}>
            Check for existing answers
          </Button>
        )}
      </form>
      {suggestions !== null && (
        <div className="space-y-2">
          {suggestions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No existing answers found.</p>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">These may already answer it:</p>
              <ul aria-label="Existing answers" className="space-y-2">
                {suggestions.map((s) => (
                  <li key={`${s.kind}-${s.id}`} className="text-sm">
                    <Link href={s.link}>{s.title}</Link>
                    <span className="ml-2 text-[11px] text-muted-foreground uppercase">{SUGGESTION_KIND[s.kind] ?? s.kind}</span>
                    {s.snippet && <p className="text-xs text-muted-foreground">{s.snippet}</p>}
                  </li>
                ))}
              </ul>
            </>
          )}
          <Button onClick={() => void ask()} disabled={busy}>
            Ask anyway
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
    </section>
  );
}
