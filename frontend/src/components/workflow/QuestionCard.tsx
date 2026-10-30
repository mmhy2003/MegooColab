"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Markdown } from "@/components/ui/Markdown";
import { api, ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import type { ActivityItem, ActivityQuestion, MockupInfo } from "@/lib/types";

import { MockupFrame } from "./MockupFrame";

const MAX_ANSWER = 4000;
const OTHER = "\u0000other"; // cannot collide with a choice id ([a-z0-9_-])

export function QuestionCard({
  item,
  taskKey,
  canAct,
  readOnly = false,
  onAnswered,
}: {
  item: ActivityItem;
  taskKey: string;
  /** the viewer may answer (workflow.can_act) */
  canAct: boolean;
  /** a read-only view: nobody answers from here */
  readOnly?: boolean;
  /** called after every answer attempt, also a conflicting one, so the thread can refetch */
  onAnswered?: () => void;
}) {
  const q = item.question as unknown as ActivityQuestion;
  const client = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [text, setText] = useState("");
  const textRef = useRef("");
  useEffect(() => {
    textRef.current = text;
  }, [text]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const open = q.status === "open";
  const answerable = canAct && !readOnly && open;

  const mockups = useQuery({
    queryKey: qk.mockups(taskKey),
    queryFn: () => api<MockupInfo[]>(`/api/tasks/${taskKey}/mockups`),
    enabled: !!q.mockup,
  });
  const mockup = q.mockup ? mockups.data?.find((m) => m.id === q.mockup!.id) : undefined;
  // a mockup click only preselects; a person has to press "Send answer". It never replaces typed text.
  const preselect = useCallback((choice: string) => setSelected((cur) => (cur === OTHER && textRef.current.trim() ? cur : choice)), []);

  // recommended first, otherwise the agent's order
  const choices = [...q.choices].sort((a, b) => Number(!!b.recommended) - Number(!!a.recommended));
  const label = (id: string) => q.choices.find((c) => c.id === id)?.label ?? id;
  const other = selected === OTHER;
  const ready = selected !== null && (!other || text.trim().length > 0);
  const sendSelected = () => {
    if (ready) void send(other ? { text: text.trim() } : { choice: selected! });
  };

  const send = async (json: { choice: string } | { text: string }) => {
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await api(`/api/tasks/${taskKey}/questions/${q.id}/answer`, { method: "POST", json });
    } catch (err) {
      setError(err instanceof ApiError && err.detail === "already_decided" ? "Someone already answered." : errorMessage(err));
    } finally {
      // also after a failure: a 409 means the question moved on
      await Promise.all([
        client.invalidateQueries({ queryKey: qk.activity(taskKey) }),
        client.invalidateQueries({ queryKey: qk.workflow(taskKey) }),
        client.invalidateQueries({ queryKey: qk.agentRuns(taskKey) }),
        client.invalidateQueries({ queryKey: qk.task(taskKey) }),
      ]);
      setBusy(false);
      onAnswered?.();
    }
  };

  return (
    // data-waiting: the task's "waiting on you" button jumps here (JumpButtons)
    <div data-waiting={answerable ? "question" : undefined} className={`card min-w-0 flex-1 space-y-2 px-3 py-2 ${q.status === "withdrawn" ? "opacity-60" : ""}`}>
      <p className="text-xs text-muted-foreground">
        <span className="text-fg">Agent question</span>
        {q.status === "withdrawn" && <> · withdrawn</>}
        {q.status === "answered" && <> · answered</>}
      </p>
      <Markdown>{q.body}</Markdown>
      {q.mockup && mockups.error && <p className="text-xs text-pink">Couldn&apos;t load the mockup.</p>}
      {q.mockup && mockup && (
        <MockupFrame mockupId={mockup.id} version={mockup.version} title={mockup.title} choices={mockup.choices} onChoice={answerable ? preselect : noop} />
      )}

      {answerable ? (
        <div className="space-y-2">
          <ul className="space-y-1">
            {choices.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  aria-pressed={selected === c.id}
                  disabled={busy}
                  onClick={() => void send({ choice: c.id })}
                  className={`w-full rounded border px-2 py-1 text-left text-sm ${selected === c.id ? "border-cyan bg-surface-2" : "border-line hover:border-cyan"}`}
                >
                  <span className="font-semibold">{c.label}</span>
                  {c.recommended && <span className="text-cyan-ink"> (Recommended)</span>}
                  {c.description && <span className="block text-xs text-muted-foreground">{c.description}</span>}
                </button>
              </li>
            ))}
            <li>
              <button
                type="button"
                aria-pressed={other}
                disabled={busy}
                onClick={() => setSelected(OTHER)}
                className={`w-full rounded border px-2 py-1 text-left text-sm ${other ? "border-cyan bg-surface-2" : "border-line hover:border-cyan"}`}
              >
                Other
              </button>
            </li>
          </ul>
          {selected !== null && !other && !q.choices.some((c) => c.id === selected) && (
            <p className="text-xs text-muted-foreground">Selected in the mockup: {selected}</p>
          )}
          {other && (
            <div className="space-y-1">
              <textarea
                aria-label="Your answer"
                className="w-full rounded border border-line bg-surface-2 px-2 py-1 text-sm"
                rows={3}
                maxLength={MAX_ANSWER}
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
              <p className="text-right text-xs text-muted-foreground">
                {text.length}/{MAX_ANSWER}
              </p>
            </div>
          )}
          <Button disabled={!ready || busy} onClick={sendSelected}>
            Send answer
          </Button>
        </div>
      ) : (
        <>
          {q.choices.length > 0 && (
            <ul className="space-y-0.5 text-xs text-muted-foreground">
              {choices.map((c) => (
                <li key={c.id}>
                  <span className="text-fg">{c.label}</span>
                  {c.recommended && " (Recommended)"}
                  {c.description && ` — ${c.description}`}
                </li>
              ))}
            </ul>
          )}
          {open && (
            <p className="text-xs text-muted-foreground">
              {canAct ? "This is a read-only view." : "Waiting on the agent's owner, a project manager or an admin to answer."}
            </p>
          )}
        </>
      )}

      {q.status === "answered" && (
        <p className="text-sm">
          <span className="text-muted-foreground">{q.answered_by?.name ?? "Someone"} answered: </span>
          {q.answer_choice ? label(q.answer_choice) : null}
          {q.answer_choice && q.answer_text ? " — " : null}
          {q.answer_text}
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-pink">
          {error}
        </p>
      )}
    </div>
  );
}

function noop() {}
