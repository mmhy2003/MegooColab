import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
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

export function useDocuments(key: string) {
  return useQuery({ queryKey: qk.documents(key), queryFn: () => api<DocumentInfo[]>(`/api/tasks/${key}/documents`) });
}

/** Plain words for each escalation reason; an unknown code stays readable. */
export const ESCALATION_REASON_TEXT: Record<string, string> = {
  retries_exhausted: "The agent's runs failed 3 times in a row.",
  pr_closed: "The pull request was closed without being merged.",
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
export const ACCEPTABLE_REASONS = ["review_rounds_exhausted", "final_review_not_clean", "enforcement_violation", "pr_closed"];

export const FINISHING_LABEL: Record<FinishingOption, string> = {
  merge_local: "Merge locally",
  pull_request: "Open a pull request",
  keep_branch: "Keep the branch",
};

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
