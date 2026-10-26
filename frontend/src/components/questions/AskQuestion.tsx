"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import {
  type AskQuestionOut,
  type QuestionSuggestion,
  questionKeys,
  useQuestionTargets,
} from "@/lib/questions";

const BODY_MAX = 4000;
const CONTEXT_MAX = 8000;

const SUGGESTION_KIND: Record<string, string> = { question: "Earlier answer", kb: "Knowledge Base", memory: "Memory" };

const FIELD ="w-full rounded border border-line bg-surface-2 px-3 py-2 text-sm text-fg focus:border-cyan focus:outline-none";

/** Ask another project (A2A-1): existing answers are offered first (A2A-6), then "Ask anyway". */
export function AskQuestion({ taskKey, onAsked }: { taskKey?: string; onAsked?: (id: string) => void }) {
  const client = useQueryClient();
  const targets = useQuestionTargets();
  const [project, setProject] = useState("");
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
      const out = await api<AskQuestionOut>("/api/questions", {
        method: "POST",
        json: { project_key: project, body: body.trim(), context: context.trim(), task_key: taskKey ?? null },
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
        <div className="flex flex-col gap-1">
          <label htmlFor="q-body" className="text-xs tracking-wider text-muted uppercase">
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
          <label htmlFor="q-context" className="text-xs tracking-wider text-muted uppercase">
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
            <p className="text-sm text-muted">No existing answers found.</p>
          ) : (
            <>
              <p className="text-sm text-muted">These may already answer it:</p>
              <ul aria-label="Existing answers" className="space-y-2">
                {suggestions.map((s) => (
                  <li key={`${s.kind}-${s.id}`} className="text-sm">
                    <Link href={s.link}>{s.title}</Link>
                    <span className="ml-2 text-[11px] text-muted uppercase">{SUGGESTION_KIND[s.kind] ?? s.kind}</span>
                    {s.snippet && <p className="text-xs text-muted">{s.snippet}</p>}
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
