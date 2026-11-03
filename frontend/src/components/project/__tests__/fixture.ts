import type { Project } from "@/lib/types";

export function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", key: "PAY", name: "Payments", description: "", sprints_enabled: true, finishing_option: "pull_request",
    pr_review: "none", pr_reviewer_agent_id: null, commit_docs_to_repo: false, send_back_on_changes_requested: false, team_ids: [], status: "active",
    created_at: "2026-10-01T00:00:00Z", ...over,
  };
}
