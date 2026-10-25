import { describe, expect, it } from "vitest";

import { runReasonText } from "@/lib/agents";

describe("runReasonText", () => {
  it("says what each runner failure code means", () => {
    expect(runReasonText("mcp_http_unsupported")).toBe("the agent can't reach MegooColab's MCP server over HTTP");
    expect(runReasonText("worktree_failed")).toBe("the runner couldn't prepare the task's worktree");
    expect(runReasonText("not_bound")).toBe("the agent isn't set up for this project");
    expect(runReasonText("files_failed")).toBe("the runner couldn't write the design and plan files");
    expect(runReasonText("commit_failed")).toBe("the runner couldn't commit the design and plan documents");
    expect(runReasonText("adapter_start_failed")).toBe("the agent program didn't start");
    expect(runReasonText("initialize_failed")).toBe("the agent program didn't respond when starting");
    expect(runReasonText("session_failed")).toBe("the agent couldn't open a session");
    expect(runReasonText("prompt_failed")).toBe("the agent stopped while working");
    expect(runReasonText("invalid_run_files")).toBe("the run's files were not valid");
    expect(runReasonText("busy")).toBe("the agent was busy");
  });

  it("keeps an unknown code readable", () => {
    expect(runReasonText("something_new")).toBe("something new");
  });
});
