import { describe, expect, it } from "vitest";

import { testRunText, type TestRun } from "@/lib/workflow";

const run = (extra: Partial<TestRun>): TestRun => ({
  id: "t1",
  stage: "build",
  step: 1,
  command: "uv run pytest",
  passed: true,
  total: null,
  failed: null,
  skipped: null,
  failing: [],
  author: "Bot",
  created_at: "2026-10-27T10:00:00Z",
  ...extra,
});

describe("testRunText", () => {
  it("says what a test run showed", () => {
    // total counts every test: passed = total - failed - skipped
    expect(testRunText(run({ total: 143, failed: 0, skipped: 1 }))).toBe("✓ 142 passed, 1 skipped — uv run pytest");
    expect(testRunText(run({ passed: false, total: 10, failed: 3, failing: ["test_a", "test_b", "test_c"] }))).toBe(
      "✗ 3 failed: test_a, test_b, test_c — uv run pytest",
    );
    expect(testRunText(run({}))).toBe("✓ passed — uv run pytest");
    expect(testRunText(run({ passed: false }))).toBe("✗ failed — uv run pytest");
  });
});

describe("escalations of a task sent back by its pull request", () => {
  it("are worded and can be accepted", async () => {
    const { escalationReasonText, ACCEPTABLE_REASONS } = await import("@/lib/workflow");
    expect(escalationReasonText("pr_fix_rounds_exhausted")).toBe("Changes were requested again after 3 fix rounds.");
    expect(escalationReasonText("pr_fix_incomplete")).toBe("The fix run ended without pushing a fix with passing tests.");
    expect(ACCEPTABLE_REASONS).toEqual(expect.arrayContaining(["pr_fix_rounds_exhausted", "pr_fix_incomplete"]));
  });
});

describe("escalations of an agent's review", () => {
  it("are worded and can be accepted", async () => {
    const { escalationReasonText, ACCEPTABLE_REASONS } = await import("@/lib/workflow");
    expect(escalationReasonText("agent_merge_failed")).toBe("The agent approved the pull request but couldn't merge it.");
    expect(escalationReasonText("agent_review_incomplete")).toBe("The reviewer ended its run without a verdict.");
    expect(escalationReasonText("agent_review_unavailable")).toBe("The chosen reviewer can't work on this repository.");
    expect(ACCEPTABLE_REASONS).toEqual(expect.arrayContaining(["agent_merge_failed", "agent_review_incomplete", "agent_review_unavailable"]));
  });
});

describe("an agent's merge that can't be confirmed", () => {
  it("is worded, can be accepted, and the quiet wait has a name", async () => {
    const { escalationReasonText, ACCEPTABLE_REASONS, needsText } = await import("@/lib/workflow");
    expect(escalationReasonText("merge_not_confirmed")).toBe("The agent merged the pull request, but MegooColab couldn't confirm it.");
    expect(ACCEPTABLE_REASONS).toContain("merge_not_confirmed");
    expect(needsText("merge_confirmation")).toBe("Agent merged · confirming");
  });
});
