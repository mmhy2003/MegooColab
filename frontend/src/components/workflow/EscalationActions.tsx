"use client";

import { Button } from "@/components/ui/Button";
import { HOST_NAME, pullRequestProblem } from "@/lib/git";
import type { Workflow } from "@/lib/types";
import { ACCEPTABLE_REASONS, escalationReasonText } from "@/lib/workflow";

export type EscalationAction = "retry" | "accept" | "pause";

/** Why an unconfirmed merge is unconfirmed: nothing reads it any more, what MegooColab can't read, else what the host
 * still shows. */
function unconfirmedWhy(wf: Workflow): string | null {
  const pr = wf.pull_request;
  if (wf.escalation_reason !== "merge_not_confirmed" || !pr) return null;
  if (!pr.tracked) return "MegooColab no longer follows this pull request (its git connection was removed).";
  if (pr.error) return pullRequestProblem(pr.error, pr.host ?? null);
  if (pr.state === "open") return `${pr.host ? HOST_NAME[pr.host] : "The git host"} still shows it open.`;
  return null;
}

/** A workflow stopped on an escalation: why, and Retry, Accept (Mark merged for an unconfirmed merge) and Pause for
 * those who decide; the others are told who does. On a task's workflow panel and in a chat. */
export function EscalationActions({ wf, canDecide, busy, onDecide }: {
  wf: Workflow;
  canDecide: boolean;
  busy: boolean;
  onDecide: (action: EscalationAction) => void;
}) {
  const why = unconfirmedWhy(wf);
  return (
    // data-waiting: the "waiting on you" button jumps here (JumpButtons)
    <div data-waiting={canDecide ? "escalation" : undefined} className="space-y-2 rounded border border-pink/60 p-2">
      <p>{escalationReasonText(wf.escalation_reason)}</p>
      {why && <p className="text-xs text-muted-foreground">{why}</p>}
      {canDecide ? (
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy} onClick={() => onDecide("retry")}>Retry</Button>
          {wf.escalation_reason && ACCEPTABLE_REASONS.includes(wf.escalation_reason) && (
            <Button variant="ghost" disabled={busy} onClick={() => onDecide("accept")}>
              {wf.escalation_reason === "merge_not_confirmed" ? "Mark merged" : "Accept"}
            </Button>
          )}
          <Button variant="danger" disabled={busy} onClick={() => onDecide("pause")}>Pause</Button>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          {wf.can_act ? "This is a read-only view." : "Waiting on the agent’s owner or a project manager."}
        </p>
      )}
    </div>
  );
}
