import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProjectsCard } from "@/components/dashboard/ProjectsCard";

afterEach(cleanup);

describe("ProjectsCard", () => {
  it("shows progress, open and late counts", () => {
    render(
      <ProjectsCard
        projects={[
          { key: "PAY", name: "Payments", open: 4, in_progress: 2, done: 4, late: 1 },
          { key: "OPS", name: "Infrastructure", open: 3, in_progress: 0, done: 1, late: 0 },
        ]}
      />,
    );
    expect(screen.getByRole("link", { name: "PAY" })).toHaveAttribute("href", "/projects/PAY/board");
    expect(screen.getByText("1 late")).toHaveClass("text-pink");
    expect(screen.getAllByText(/late/)).toHaveLength(1);
    const bar = screen.getByRole("img", { name: "PAY: 4 done, 2 in progress, 2 to do" });
    expect(Array.from(bar.children).map((b) => (b as HTMLElement).style.width)).toEqual(["50%", "25%"]);
    expect(screen.getByRole("link", { name: /All/ })).toHaveAttribute("href", "/projects");
  });

  it("says when no project is in scope", () => {
    render(<ProjectsCard projects={[]} />);
    expect(screen.getByText("No projects in scope.")).toBeInTheDocument();
  });
});
