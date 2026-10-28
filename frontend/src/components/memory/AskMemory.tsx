"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { MemAnswer } from "@/lib/memory";
import { useProjects } from "@/lib/project";

const QUESTION_MAX = 1000;

/** Ask the memory (MEM-5): the answer cites the conclusions it used. */
export function AskMemory() {
  const projects = useProjects();
  const [question, setQuestion] = useState("");
  const [project, setProject] = useState("");
  const [answer, setAnswer] = useState<MemAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <section className="card space-y-3 p-4" aria-label="Ask the memory">
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          setBusy(true);
          try {
            setAnswer(
              await api<MemAnswer>("/api/memory/ask", {
                method: "POST",
                json: { question: question.trim(), project_key: project || null },
              }),
            );
          } catch (err) {
            setAnswer(null);
            setError(errorMessage(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="flex flex-col gap-1">
          <label htmlFor="mem-question" className="text-xs tracking-wider text-muted-foreground uppercase">
            Question
          </label>
          <textarea
            id="mem-question"
            required
            maxLength={QUESTION_MAX}
            rows={2}
            placeholder="What is the Payments project trying to achieve this quarter?"
            className="w-full rounded border border-line bg-surface-2 px-3 py-2 text-sm text-fg focus:border-cyan focus:outline-none"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <label htmlFor="mem-project" className="text-xs tracking-wider text-muted-foreground uppercase">
              Project (optional)
            </label>
            <select
              id="mem-project"
              className="rounded border border-line bg-surface-2 px-2 py-2 text-sm text-fg"
              value={project}
              onChange={(e) => setProject(e.target.value)}
            >
              <option value="">Any</option>
              {(projects.data ?? []).map((p) => (
                <option key={p.id} value={p.key}>
                  {p.key} — {p.name}
                </option>
              ))}
            </select>
          </div>
          <Button type="submit" disabled={busy || !question.trim()}>
            Ask
          </Button>
        </div>
      </form>
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
      {answer && (
        <div className="space-y-2">
          <div className="kb-prose">
            <Markdown>{answer.answer_md}</Markdown>
          </div>
          {answer.cited.length > 0 && (
            <ol aria-label="Sources" className="space-y-1 text-sm">
              {answer.cited.map((c, i) => (
                <li key={c.id} className="flex gap-2">
                  <span className="font-mono text-xs text-muted-foreground">[{i + 1}]</span>
                  <span>
                    {c.text} —{" "}
                    <Link href={`/memory/entity/${c.entity_id}`} className="text-xs">
                      {c.entity_name}
                    </Link>
                  </span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </section>
  );
}
