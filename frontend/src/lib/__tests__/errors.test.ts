import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";

describe("errorMessage for rate limits", () => {
  it("says when to try again", () => {
    expect(errorMessage(new ApiError(429, "rate_limited", 840))).toBe("Too many attempts. Try again in 14 minutes.");
    expect(errorMessage(new ApiError(429, "rate_limited", 841))).toBe("Too many attempts. Try again in 15 minutes.");
    expect(errorMessage(new ApiError(429, "rate_limited", 60))).toBe("Too many attempts. Try again in 1 minute.");
    expect(errorMessage(new ApiError(429, "rate_limited", 30))).toBe("Too many attempts. Try again in 30 seconds.");
    expect(errorMessage(new ApiError(429, "rate_limited", 1))).toBe("Too many attempts. Try again in 1 second.");
  });

  it("still says something when the wait is unknown", () => {
    expect(errorMessage(new ApiError(429, "rate_limited"))).toBe("Too many attempts. Try again later.");
  });

  it("leaves other 429s their own message", () => {
    expect(errorMessage(new ApiError(429, "too_many_open_questions"))).not.toMatch(/Too many attempts/);
  });
});
