import { describe, expect, it } from "vitest";

import { run } from "@/components/dashboard/__tests__/fixture";
import { runStatus } from "@/lib/runs";

const idle = { stage: null, step: null, steps_total: null };

describe("runStatus", () => {
  it("gives the Build step", () => {
    expect(runStatus(run())).toBe("Build · Step 2 of 3");
  });

  it("gives the Review round past the first", () => {
    expect(runStatus(run({ stage: "review", step: null, steps_total: null, review_round: 2 }))).toBe("Review, round 2");
    expect(runStatus(run({ stage: "review", step: null, steps_total: null, review_round: 1 }))).toBe("Review");
  });

  it("says what a run with no stage is doing", () => {
    expect(runStatus(run({ ...idle, kind: "question" }))).toBe("Answering");
    expect(runStatus(run({ ...idle, kind: "cron" }))).toBe("Running");
    expect(runStatus(run({ ...idle, kind: "draft" }))).toBe("Writing");
    expect(runStatus(run({ ...idle, kind: "chat" }))).toBe("Working");
  });
});
