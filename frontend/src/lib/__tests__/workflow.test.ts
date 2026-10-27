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
