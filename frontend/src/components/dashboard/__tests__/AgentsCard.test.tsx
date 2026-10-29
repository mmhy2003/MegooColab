import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AgentsCard } from "@/components/dashboard/AgentsCard";

import { agent } from "./fixture";

afterEach(cleanup);

describe("AgentsCard", () => {
  it("labels Working, Idle and Offline with runs today", () => {
    render(
      <AgentsCard
        isAdmin={false}
        agents={[agent(), agent({ id: "a2", name: "Docs bot", status: "online", runs_today: 1 }), agent({ id: "a3", name: "Laptop", status: "offline", runs_today: 0 })]}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Vera's Claude CodeWorking9 runs today");
    expect(rows[1]).toHaveTextContent("Docs botIdle1 run today");
    expect(rows[2]).toHaveTextContent("LaptopOffline0 runs today");
    expect(screen.getByRole("link", { name: /Manage/ })).toHaveAttribute("href", "/settings/agents");
  });

  it("says when no agent is in scope", () => {
    render(<AgentsCard agents={[]} isAdmin />);
    expect(screen.getByText("No agents in scope.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Manage/ })).toHaveAttribute("href", "/admin/agents");
  });

  it("tells an agent working in a project outside the view apart", () => {
    render(<AgentsCard isAdmin={false} agents={[agent({ status: "busy_elsewhere", runs_today: 0 })]} />);
    expect(screen.getByRole("listitem")).toHaveTextContent("Vera's Claude CodeWorking elsewhere0 runs today");
  });
});
