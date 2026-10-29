import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
import type { components } from "@/lib/api-types";
import type { DocumentInfo, MockupInfo, Workflow, WorkflowNeeds, WorkflowStage } from "@/lib/types";

export type FinishingOption = Workflow["finishing_option"];

export const STAGES: { id: WorkflowStage; label: string }[] = [
  { id: "brainstorm", label: "Brainstorm" },
  { id: "design", label: "Design" },
  { id: "plan", label: "Plan" },
  { id: "build", label: "Build" },
  { id: "review", label: "Review" },
  { id: "done", label: "Done" },
];

export function stageIndex(stage: WorkflowStage): number {
  return STAGES.findIndex((s) => s.id === stage);
}

export function stageLabel(stage: WorkflowStage): string {
  return STAGES[stageIndex(stage)].label;
}

const NEEDS_TEXT: Record<WorkflowNeeds, string> = {
  question: "Answer the agent's question",
  design_approval: "Approve the design",
  plan_approval: "Approve the plan",
  escalation: "Decide how to continue",
  human_code_review: "Approve the PR",
};

export function needsText(needs: WorkflowNeeds): string {
  return NEEDS_TEXT[needs];
}

export function useWorkflow(key: string) {
  return useQuery({ queryKey: qk.workflow(key), queryFn: () => api<Workflow>(`/api/tasks/${key}/workflow`) });
}

/** The task's mockups, oldest first: question mockups and shown ones share one version sequence. */
export function useMockups(key: string) {
  return useQuery({ queryKey: qk.mockups(key), queryFn: () => api<MockupInfo[]>(`/api/tasks/${key}/mockups`) });
}

export type Decision = components["schemas"]["DecisionOut"];
export type TestRun = components["schemas"]["TestRunOut"];
export type RunRecords = components["schemas"]["RecordsOut"];

/** What the agent decided on its own and the test runs it recorded (Plan 8). */
export function useRunRecords(key: string) {
  return useQuery({ queryKey: qk.records(key), queryFn: () => api<RunRecords>(`/api/tasks/${key}/records`) });
}

/** One line for a recorded test run: "✓ 142 passed, 1 skipped — cmd" or "✗ 3 failed: a, b, c — cmd". */
export function testRunText(run: TestRun): string {
  const tail = ` — ${run.command}`;
  if (!run.passed) {
    const names = run.failing.length ? `: ${run.failing.join(", ")}` : "";
    return `✗ ${run.failed != null ? `${run.failed} failed` : "failed"}${names}${tail}`;
  }
  if (run.total == null) return `✓ passed${tail}`;
  const passed = run.total - (run.failed ?? 0) - (run.skipped ?? 0);
  return `✓ ${passed} passed${run.skipped ? `, ${run.skipped} skipped` : ""}${tail}`;
}

export function useDocuments(key: string) {
  return useQuery({ queryKey: qk.documents(key), queryFn: () => api<DocumentInfo[]>(`/api/tasks/${key}/documents`) });
}

/** Plain words for each escalation reason; an unknown code stays readable. */
export const ESCALATION_REASON_TEXT: Record<string, string> = {
  retries_exhausted: "The agent's runs failed 3 times in a row.",
  pr_closed: "The pull request was closed without being merged.",
  back_merge_pr_closed: "The back-merge pull request (into the default branch) was closed without being merged.",
  no_output: "The agent finished twice without a question or a design.",
  enforcement_violation: "The agent changed the repository during a read-only stage.",
  step_incomplete: "The agent ended its run without finishing the step.",
  review_incomplete: "The reviewer ended its run without a verdict.",
  review_rounds_exhausted: "The step still had review findings after 3 review rounds.",
  final_review_not_clean: "The final review still had findings after one fix round.",
  finish_incomplete: "The agent ended its run without finishing the work.",
  engine_error: "MegooColab hit an internal error handling the last run.",
};

export function escalationReasonText(code: string | null): string {
  if (!code) return "The workflow needs a decision.";
  return ESCALATION_REASON_TEXT[code] ?? code.replace(/_/g, " ");
}

/** "Accept" is offered only where treating the work as passed makes sense. */
export const ACCEPTABLE_REASONS = ["review_rounds_exhausted", "final_review_not_clean", "enforcement_violation", "pr_closed",
  "back_merge_pr_closed"];

export const FINISHING_LABEL: Record<FinishingOption, string> = {
  merge_local: "Merge locally",
  pull_request: "Open a pull request",
  keep_branch: "Keep the branch",
};

/** Where the work starts and is delivered (Branch from): recorded once the task's branch exists, else a preview. */
/** `toldAgent`: a started connect-only workflow, whose agent makes its own branch and never reports where it started. */
export function branchLine(
  start: string | null | undefined,
  backMergeInto: string | null | undefined,
  branchFrom: string | null | undefined,
  toldAgent = false,
): string {
  if (start && backMergeInto) return `Starts from ${start}. Delivers to ${start}, then ${backMergeInto}.`;
  if (start) return `Starts from ${start}. Delivers to ${start}.`;
  if (toldAgent) return `The agent was told to start from ${branchFrom ?? "the default branch"}.`;
  if (branchFrom) return `Will start from ${branchFrom}.`;
  return "Will start from the default branch.";
}

/** One line for the panel: "Running: Build, step 2 of 5", "Waiting: Approve the plan". */
export function statusLine(wf: Pick<Workflow, "stage" | "status" | "needs" | "current_step" | "steps_total">): string {
  switch (wf.status) {
    case "idle":
      return "Not started";
    case "paused":
      return "Paused";
    case "finished":
      return "Finished";
    case "waiting_human":
      return `Waiting: ${wf.needs ? needsText(wf.needs) : stageLabel(wf.stage)}`;
    default: {
      const step = wf.stage === "build" && wf.current_step && wf.steps_total ? `, step ${wf.current_step} of ${wf.steps_total}` : "";
      return `Running: ${stageLabel(wf.stage)}${step}`;
    }
  }
}
