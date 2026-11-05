import { describe, expect, it } from "vitest";

import { limitedText, pullRequestProblem, pullRequestText, TOKEN_HELP, type PullRequest } from "@/lib/git";

describe("pullRequestProblem", () => {
  it("maps every code to its row", () => {
    const rows: [string, string][] = [
      ["forbidden", "GitHub refused the token (forbidden). It needs Pull requests, Commit statuses and Checks (read)."],
      ["unauthorized", "GitHub rejected the token. It may have expired or been revoked."],
      ["not_found", "The token can't see this repository or pull request."],
      ["rate_limited", "GitHub is limiting requests. MegooColab will try again."],
      ["unreachable", "GitHub couldn't be reached."],
      ["bad_token", "The saved token can't be read. Save it again in Settings › Git."],
      ["url_mismatch", "The pull request isn't on this connection's address."],
      ["bad_response", "GitHub sent something MegooColab didn't understand."],
      ["error", "GitHub sent something MegooColab didn't understand."],
    ];
    for (const [code, text] of rows) expect(pullRequestProblem(code, "github")).toBe(text);
  });

  it("names the host and uses its own permission words", () => {
    expect(pullRequestProblem("unauthorized", "gitlab")).toMatch(/^GitLab rejected the token/);
    expect(pullRequestProblem("forbidden", "gitlab")).toContain("read_api");
    expect(pullRequestProblem("forbidden", "gitea")).toContain("read:repository");
    expect(pullRequestProblem("forbidden", "gitlab")).not.toContain("Commit statuses");
  });
});

describe("limitedText", () => {
  it("says what the token can't read", () => {
    expect(limitedText(null)).toBeNull();
    expect(limitedText("checks")).toBe("Checks unknown: the token can't read commit statuses or checks.");
    expect(limitedText("review")).toBe("Review unknown: the token can't read reviews.");
    expect(limitedText("checks,review")).toBe(
      "Checks unknown: the token can't read commit statuses or checks. Review unknown: the token can't read reviews.",
    );
  });
});

describe("TOKEN_HELP", () => {
  it("asks GitHub tokens for statuses and checks", () => {
    expect(TOKEN_HELP.github).toContain("Commit statuses");
    expect(TOKEN_HELP.github).toContain("Checks");
  });
});

describe("pullRequestText", () => {
  const pr = (extra: object) => ({ url: "u", state: "open", checks: "none", review: "none", tracked: true, ...extra }) as PullRequest;
  it("shows unknown checks and unreadable pull requests", () => {
    expect(pullRequestText(pr({ checks: "unknown" }))).toBe("PR open · checks unknown");
    expect(pullRequestText(pr({ error: "forbidden" }))).toBe("PR · can't read");
  });
});
