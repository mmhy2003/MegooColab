import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
import type { Workflow, WorkflowNeeds, WorkflowStage } from "@/lib/types";

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
