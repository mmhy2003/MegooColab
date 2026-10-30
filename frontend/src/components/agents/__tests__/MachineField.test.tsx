import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MachineField } from "@/components/agents/MachineField";
import type { AccessToken, Machine } from "@/lib/types";

const PAST = "2020-01-01T00:00:00Z";
const FUTURE = "2999-01-01T00:00:00Z";

function token(id: string, name: string, extra: Partial<AccessToken> = {}): AccessToken {
  return {
    id, name, prefix: "mgc_abcd", scopes: ["runner", "mcp"], expires_at: null, last_used_at: null,
    created_at: PAST, revoked_at: null, agents: [], ...extra,
  };
}

const TOKENS = [
  token("t-mcp", "MCP only", { scopes: ["mcp"] }),
  token("t-old", "Revoked", { revoked_at: PAST }),
  token("t-exp", "Expired", { expires_at: PAST }),
  token("t-yoga", "Yoga", { expires_at: FUTURE }),
];

function renderField(machine: Machine | null, tokens = TOKENS, onChange = vi.fn()) {
  render(<MachineField machine={machine} tokens={tokens} value={machine?.token_id ?? null} onChange={onChange} />);
  return onChange;
}

afterEach(cleanup);

describe("MachineField", () => {
  it("lists only usable runner tokens", () => {
    renderField(null);
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Not linked", "Yoga"]);
  });

  it("shows the not-linked hint", () => {
    renderField(null);
    expect(screen.getByText("Not linked to a machine — it stays offline until you pick its machine's token.")).toBeTruthy();
  });

  it("shows the expired text", () => {
    renderField({ token_id: "t-exp", name: "Expired", expired: true });
    expect(screen.getByText("Machine token expired — pick another")).toBeTruthy();
    expect(screen.queryByText(/Not linked to a machine/)).toBeNull();
  });

  it("points to Access tokens when there is no runner token", () => {
    renderField(null, [token("t-mcp", "MCP only", { scopes: ["mcp"] })]);
    expect(screen.getByText(/Create a token with the Runner scope in/).textContent).toBe(
      "Create a token with the Runner scope in Access tokens first.",
    );
    expect(screen.getByRole("link", { name: "Access tokens" }).getAttribute("href")).toBe("/settings/tokens");
  });

  it("reports the picked token", async () => {
    const onChange = renderField(null);
    await userEvent.selectOptions(screen.getByLabelText("Machine"), "t-yoga");
    expect(onChange).toHaveBeenCalledWith("t-yoga");
    await userEvent.selectOptions(screen.getByLabelText("Machine"), "");
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});
