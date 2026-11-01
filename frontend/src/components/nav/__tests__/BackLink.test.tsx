import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { BackLink } from "@/components/nav/BackLink";
import { recordVisit } from "@/lib/backNav";

beforeEach(() => sessionStorage.clear());
afterEach(cleanup);

describe("BackLink", () => {
  it("names the recorded origin", () => {
    recordVisit("/kb/search?q=retry", 'results for "retry"');
    recordVisit("/kb/doc/d1", "Plan");
    render(<BackLink area="kb-read" fallback={{ href: "/kb/s1?folder=f1", label: "Guides" }} />);
    const link = screen.getByRole("link", { name: '← Back to results for "retry"' });
    expect(link).toHaveAttribute("href", "/kb/search?q=retry");
  });

  it("falls back when nothing is recorded", () => {
    render(<BackLink area="kb-read" fallback={{ href: "/kb/s1?folder=f1", label: "Guides" }} />);
    expect(screen.getByRole("link", { name: "← Back to Guides" })).toHaveAttribute("href", "/kb/s1?folder=f1");
  });
});
