"use client";

import { Button } from "@/components/ui/Button";
import { HOST_NAME, pullRequestProblem } from "@/lib/git";
import type { Workflow } from "@/lib/types";
import { ACCEPTABLE_REASONS, escalationReasonText, type TestRun } from "@/lib/workflow";

import { FinishFailures } from "./FinishFailures";

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

/** A workflow stopped on an escalation: why, and Retry, Accept (Mark merged for an unconfirmed merge, Finish anyway for
 * tests that failed at finish) and Pause for those who decide; the others are told who does. Tests that failed at
 * finish are listed with their kinds, the diagnosis and the finish's test runs (`runs`). On a task's workflow panel and
 * in a chat. */
export function EscalationActions({ wf, canDecide, busy, onDecide, runs }: {
  wf: Workflow;
  canDecide: boolean;
  busy: boolean;
  onDecide: (action: EscalationAction) => void;
  runs?: TestRun[];
}) {
  const why = unconfirmedWhy(wf);
  const failed = wf.escalation_reason === "finish_tests_failed";
  return (
    // data-waiting: the "waiting on you" button jumps here (JumpButtons)
    <div data-waiting={canDecide ? "escalation" : undefined} className="space-y-2 rounded border border-pink/60 p-2">
      {failed && wf.finish_tests ? (
        <FinishFailures tests={wf.finish_tests} startBranch={wf.start_branch ?? null} runs={runs} />
      ) : (
        <p>{escalationReasonText(wf.escalation_reason)}</p>
      )}
      {why && <p className="text-xs text-muted-foreground">{why}</p>}
      {failed && canDecide && (
        <p className="text-xs text-muted-foreground">
          {wf.finish_tests?.delivered === false
            ? "Finish anyway records that you accepted these tests; the agent then delivers the work and lists them in the pull request."
            : "Finish anyway records that you accepted these tests and finishes the task."}
        </p>
      )}
      {canDecide ? (
        <div className="flex flex-wrap gap-2">
          <Button disabled={busy} onClick={() => onDecide("retry")}>Retry</Button>
          {wf.escalation_reason && ACCEPTABLE_REASONS.includes(wf.escalation_reason) && (
            <Button variant="ghost" disabled={busy} onClick={() => onDecide("accept")}>
              {wf.escalation_reason === "merge_not_confirmed" ? "Mark merged" : failed ? "Finish anyway" : "Accept"}
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
