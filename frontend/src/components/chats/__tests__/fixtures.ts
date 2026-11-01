import type { Chat } from "@/lib/chats";

/** A chat as the API returns it, open, in its first round. */
export function chat(over: Partial<Chat> = {}): Chat {
  return {
    id: "c1", project_key: "PAY", title: "Fix empty email", status: "open",
    agent: { id: "a1", name: "laptop-claude", program: "claude_code" }, started_by: null,
    created_at: "2026-11-01T10:00:00Z", last_activity_at: "2026-11-01T10:05:00Z", state: "talking", intent: "tell",
    can_act: true,
    rounds: [{ n: 1, key: "PAY-7", title: "Fix empty email", stage: "brainstorm", status: "running", needs: null,
      current_step: null, steps_total: null, finish_outcome: null, pr_url: null, branch: null, branch_from: null, board: null }],
    ...over,
  } as Chat;
}
