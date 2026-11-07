import { describe, expect, it } from "vitest";

import { limitedText, newTokenUrl, pullRequestProblem, pullRequestText, TOKEN_NEEDS, type PullRequest } from "@/lib/git";

describe("pullRequestProblem", () => {
  it("maps every code to its row", () => {
    const rows: [string, string][] = [
      ["forbidden", "GitHub refused the token (forbidden). It needs Pull requests and Commit statuses (read)."],
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

  it("on GitHub, says a fine-grained token can't read check runs, and what can", () => {
    expect(limitedText("checks", "github")).toBe(
      "Checks unknown: GitHub doesn't let a fine-grained token read check runs, where GitHub Actions reports. A classic token with repo shows them.",
    );
    expect(limitedText("checks,review", "github")).toBe("Checks unknown: GitHub doesn't let a fine-grained token read check runs, where GitHub Actions reports. A classic token with repo shows them. Review unknown: the token can't read reviews.");
    expect(limitedText("checks", "gitea")).toBe("Checks unknown: the token can't read commit statuses or checks.");
    expect(limitedText("checks", null)).toBe("Checks unknown: the token can't read commit statuses or checks.");
  });
});

describe("TOKEN_NEEDS", () => {
  it("asks a fine-grained GitHub token for statuses, never for Checks, and says it can't read check runs", () => {
    const [fine] = TOKEN_NEEDS.github;
    const names = fine.needs[0].permissions.map((p) => p.name);
    expect(names).toEqual(["Contents", "Metadata", "Pull requests", "Commit statuses"]);
    expect(fine.needs.flatMap((n) => n.permissions.map((p) => p.name))).not.toContain("Checks");
    expect(fine.needs[0].warning).toMatch(/can't read check runs/);
  });

  it("starts every host with the one required reason", () => {
    for (const variants of Object.values(TOKEN_NEEDS)) {
      for (const v of variants) expect(v.needs.map((n) => n.required)).toEqual([true, false, false]);
    }
  });
});

describe("newTokenUrl", () => {
  it("joins the server's address and the page, or gives up without a real address", () => {
    expect(newTokenUrl("https://git.example.com//", "/user/settings/applications")).toBe("https://git.example.com/user/settings/applications");
    expect(newTokenUrl("", "/x")).toBeNull();
    expect(newTokenUrl("git.example.com", "/x")).toBeNull();
    expect(newTokenUrl("javascript:alert(1)", "/x")).toBeNull();
  });
});

describe("pullRequestText", () => {
  const pr = (extra: object) => ({ url: "u", state: "open", checks: "none", review: "none", tracked: true, ...extra }) as PullRequest;
  it("shows unknown checks and unreadable pull requests", () => {
    expect(pullRequestText(pr({ checks: "unknown" }))).toBe("PR open · checks unknown");
    expect(pullRequestText(pr({ error: "forbidden" }))).toBe("PR · can't read");
  });
});
