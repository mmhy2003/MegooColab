import { describe, expect, it } from "vitest";

import { describeEvent } from "@/components/task/ActivityThread";
import { runReasonText } from "@/lib/agents";
import { errorMessage } from "@/lib/errors";
import { ApiError } from "@/lib/api";
import { branchLine } from "@/lib/workflow";

describe("branchLine", () => {
  it("says where the work starts and where it is delivered", () => {
    expect(branchLine("main", "develop", "main")).toBe("Starts from main. Delivers to main, then develop.");
    expect(branchLine("develop", null, null)).toBe("Starts from develop. Delivers to develop.");
    expect(branchLine(null, null, "main")).toBe("Will start from main.");
    expect(branchLine(null, null, null)).toBe("Will start from the default branch.");
  });

  it("a started connect-only workflow says what the agent was told, not what will happen", () => {
    expect(branchLine(null, null, "main", true)).toBe("The agent was told to start from main.");
    expect(branchLine(null, null, null, true)).toBe("The agent was told to start from the default branch.");
  });
});

describe("Branch from messages", () => {
  it("explains the new errors and run failures", () => {
    expect(errorMessage(new ApiError(422, "invalid_branch_name"))).toBe("That isn't a valid branch name.");
    expect(errorMessage(new ApiError(409, "branch_from_locked"))).toBe("Branch from can't change once work has started.");
    expect(runReasonText("start_branch_missing")).toBe("the branch to start from doesn't exist");
    expect(runReasonText("start_branch_fetch_failed")).toBe("the runner couldn't reach the repository to fetch the branch to start from");
    expect(runReasonText("repository_not_matched")).toBe("the agent's folder doesn't match any of the project's repositories");
  });

  it("describes where work started", () => {
    const names = { columnNames: new Map(), userNames: new Map(), agentNames: new Map() };
    expect(describeEvent("branch_started", { start_branch: "main", back_merge_into: "develop" }, names)).toBe("started work from main");
  });
});
