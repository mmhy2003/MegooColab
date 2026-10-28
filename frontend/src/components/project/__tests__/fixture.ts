import type { Project } from "@/lib/types";

export function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", key: "PAY", name: "Payments", description: "", sprints_enabled: true, finishing_option: "pull_request",
    require_human_code_review: false, commit_docs_to_repo: false, team_ids: [], status: "active",
    created_at: "2026-10-01T00:00:00Z", ...over,
  };
}
