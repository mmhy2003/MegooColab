"use client";

import { Hourglass } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { type ProjectWait, waitingFor, waitStatusLine } from "@/lib/questions";

/** The work waits for other projects' answers to questions its agent asked: what it waits for, where each question
 * stands, and what the viewer may do: answer one, withdraw one, or have the agent go on without them. */
export function ProjectWaitBanner({
  taskKey,
  waits,
  canAct,
  agentName,
  inChat = false,
  onChanged,
}: {
  taskKey: string;
  waits: ProjectWait[];
  /** may decide for the task: "Go on without it" */
  canAct: boolean;
  agentName?: string | null;
  inChat?: boolean;
  /** after a choice (also a failed one: the state may have moved on) */
  onChanged?: () => void | Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { ask, dialog } = useConfirm();
  const agent = agentName ?? "The agent";
  const one = waits.length === 1;

  const act = async (url: string) => {
    setError(null);
    setBusy(true);
    try {
      await api(url, { method: "POST" });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      await onChanged?.();
    }
  };

  return (
    <div role="status" data-project-waits className="space-y-2 rounded border border-cyan/50 p-2.5 text-sm">
      <p className="flex items-center gap-1.5 font-semibold">
        <Hourglass size={13} aria-hidden className="text-cyan-ink" />
        {`Waiting for ${waitingFor(waits.map((w) => w.ref))}`}
      </p>
      <p className="text-xs text-muted-foreground">
        {inChat
          ? `${agent} picks up again on its own when the ${one ? "answer arrives" : "answers arrive"}. Anything you send now reaches it with the ${one ? "answer" : "answers"}.`
          : `The agent asked ${one ? waits[0].project_key : "other projects"} about ${one ? "its" : "their"} code and can't go on without the ${one ? "answer" : "answers"}. It picks up again on its own when ${one ? "the answer arrives" : "they arrive"}.`}
      </p>
      <ul className="space-y-1.5">
        {waits.map((w) => (
          <li key={w.question_id} className="space-y-0.5 border-t border-line pt-1.5">
            <p className="flex items-baseline gap-1.5">
              <span className="rounded border border-line px-1 font-mono text-[11px] text-muted-foreground">{w.ref}</span>
              <span className="min-w-0 wrap-anywhere">{w.title}</span>
            </p>
            <p className={`text-xs ${w.status === "needs_human" ? "text-amber" : "text-muted-foreground"}`}>
              {waitStatusLine(w.status, w.project_key)}
            </p>
            {(w.can_answer || w.can_withdraw) && (
              <p className="flex gap-3 text-xs">
                {w.can_answer && (
                  <Link href={`/questions/${w.question_id}`} className="text-cyan-ink underline">
                    Answer it yourself
                  </Link>
                )}
                {w.can_withdraw && (
                  <button
                    type="button"
                    aria-label={`Withdraw ${w.ref}`}
                    className="text-cyan-ink underline disabled:opacity-60"
                    disabled={busy}
                    onClick={async () => {
                      const sure = await ask({
                        tone: "warn",
                        title: `Withdraw ${w.ref}?`,
                        text: `${w.project_key} stops working on it. ${one ? `${agent} picks up again without the answer.` : "The agent stops waiting for it."}`,
                        ok: "Withdraw",
                      });
                      if (sure) await act(`/api/questions/${w.question_id}/withdraw`);
                    }}
                  >
                    Withdraw
                  </button>
                )}
              </p>
            )}
          </li>
        ))}
      </ul>
      {canAct && (
        <Button variant="ghost" disabled={busy} onClick={() => void act(`/api/tasks/${taskKey}/project-waits/go-on`)}>
          Go on without it
        </Button>
      )}
      {error && <p role="alert" className="text-xs text-pink">{error}</p>}
      {dialog}
    </div>
  );
}
