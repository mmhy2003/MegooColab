import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SystemCard, systemLines } from "@/components/dashboard/SystemCard";

import { healthy } from "./fixture";

afterEach(cleanup);

const NOW = new Date("2026-10-28T10:00:00Z");
const hoursAgo = (h: number) => new Date(NOW.getTime() - h * 3_600_000).toISOString();

describe("systemLines", () => {
  it.each([
    ["no runner while agents exist", { runners: 0, agents_exist: true }, "Runners connected"],
    ["51 jobs waiting", { jobs_waiting: 51 }, "Background jobs"],
    ["the oldest job waited 301 s", { oldest_job_seconds: 301 }, "Background jobs"],
    ["search down", { search_available: false, search_documents: null }, "Search index"],
    ["no AI provider", { ai_configured: false }, "AI provider"],
    ["an AI job failed", { ai_failed_today: 1 }, "AI provider"],
    ["memory last ran 27 h ago", { memory_last_at: hoursAgo(27) }, "Memory"],
    ["the last memory run failed", { memory_last_failed: true }, "Memory"],
    ["memory never ran", { memory_last_at: null }, "Memory"],
    ["a rate limit was hit", { rate_limits_24h: 1 }, "Rate limits hit"],
  ])("needs attention when %s", (_, over, label) => {
    const lines = systemLines({ ...healthy, memory_last_at: hoursAgo(8), ...over }, NOW);
    expect(lines.filter((l) => l.attention).map((l) => l.label)).toEqual([label]);
  });

  it("is all green when healthy, with no runners and no agents", () => {
    const lines = systemLines({ ...healthy, runners: 0, agents_exist: false, memory_last_at: hoursAgo(8) }, NOW);
    expect(lines.map((l) => l.label)).toEqual([
      "Runners connected", "Background jobs", "Search index", "AI provider", "Memory", "Rate limits hit",
    ]);
    expect(lines.every((l) => !l.attention)).toBe(true);
  });

  it("words each value", () => {
    const values = systemLines({ ...healthy, memory_last_at: hoursAgo(8) }, NOW).map((l) => l.value);
    expect(values.slice(0, 4)).toEqual(["2 connected", "0 waiting", "Available · 120 items", "OK · 12 jobs today"]);
    expect(values[4]).toMatch(/^last learned \d\d:\d\d$/);
    expect(values[5]).toBe("0 in 24 h");
    const down = systemLines({ ...healthy, search_available: false, search_documents: null, ai_configured: false, memory_last_at: null }, NOW);
    expect(down.map((l) => l.value).slice(2, 5)).toEqual(["Unavailable", "Not configured", "never"]);
  });
});

describe("SystemCard", () => {
  it("is marked admins only", () => {
    render(<SystemCard system={healthy} />);
    expect(screen.getByText("admins only")).toBeInTheDocument();
    expect(screen.getByText("Runners connected")).toBeInTheDocument();
  });
});
