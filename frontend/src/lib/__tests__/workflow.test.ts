import { describe, expect, it } from "vitest";

import { finishedWithSummary, finishTestsSummary, testRunText, type TestRun } from "@/lib/workflow";

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
  on_base: false,
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

  it("says when a run was made on the start commit", () => {
    expect(testRunText(run({ passed: false, failed: 1, failing: ["a"], on_base: true }))).toBe(
      "✗ 1 failed: a — uv run pytest (on the start commit)",
    );
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

describe("work left uncommitted", () => {
  it("is worded, and can only be retried (back to its agent to commit)", async () => {
    const { escalationReasonText, ACCEPTABLE_REASONS } = await import("@/lib/workflow");
    expect(escalationReasonText("uncommitted_changes")).toBe("The agent left its changes uncommitted, so they can't be reviewed.");
    expect(ACCEPTABLE_REASONS).not.toContain("uncommitted_changes");
  });
});

describe("failing tests at finish", () => {
  const f = (name: string, kind: "new" | "base" | "flaky") => ({ name, kind });

  it("are counted by kind on the card", () => {
    const failures = [f("a", "new"), f("b", "base"), f("c", "flaky")];
    expect(finishTestsSummary({ failures, failing_total: 3 }, "develop")).toBe(
      "Tests failed at finish: 3 failing (1 new, 1 also fails on develop, 1 flaky)",
    );
    expect(finishTestsSummary({ failures: [f("a", "new")] }, "develop")).toBe("Tests failed at finish: 1 failing (1 new)");
    expect(finishTestsSummary({ failures: [f("b", "base")] }, null)).toBe(
      "Tests failed at finish: 1 failing (1 also fails on the start branch)",
    );
  });

  it("count the tests the agent didn't list", () => {
    const failures = Array.from({ length: 20 }, (_, i) => f(`t${i}`, "new"));
    expect(finishTestsSummary({ failures, failing_total: 25 }, "develop")).toBe(
      "Tests failed at finish: 25 failing (20 new, 5 not listed)",
    );
  });

  it("fall back to a plain line without names", () => {
    expect(finishTestsSummary({ failures: [], failing_total: null }, "develop")).toBe(
      "The agent reported that the tests did not pass.",
    );
  });

  it("are summed up once the task finished with them", () => {
    expect(finishedWithSummary({ failures: [f("b", "base"), f("c", "flaky")], settled: "known" }, "develop")).toBe(
      "Finished with 2 known failing tests: 1 also fails on develop, 1 flaky",
    );
    expect(finishedWithSummary({ failures: [f("c", "flaky")], settled: "known" }, "develop")).toBe(
      "Finished with 1 known failing test: 1 flaky",
    );
    const three = [f("a", "new"), f("b", "new"), f("c", "base")];
    expect(finishedWithSummary({ failures: three, settled: "accepted", accepted_by: "Ann" }, "develop")).toBe(
      "Finished with 3 failing tests accepted by Ann",
    );
    expect(finishedWithSummary({ failures: [], settled: "accepted", accepted_by: "Ann" }, "develop")).toBe(
      "Finished with failing tests accepted by Ann",
    );
  });
});

describe("escalations of failing tests at finish", () => {
  it("are worded and can be accepted", async () => {
    const { escalationReasonText, ACCEPTABLE_REASONS } = await import("@/lib/workflow");
    expect(escalationReasonText("finish_tests_failed")).toBe("Tests failed at finish.");
    expect(ACCEPTABLE_REASONS).toContain("finish_tests_failed");
  });
});
