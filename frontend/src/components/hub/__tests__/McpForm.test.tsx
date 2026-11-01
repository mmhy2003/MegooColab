import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { McpForm, type McpBody } from "@/components/hub/McpForm";
import { ApiError } from "@/lib/api";

afterEach(cleanup);

describe("McpForm", () => {
  it("builds a command MCP with arguments and a secret variable", async () => {
    const onSubmit = vi.fn<(body: McpBody) => Promise<void>>(async () => {});
    render(<McpForm submitLabel="Save" onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "context7" } });
    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "stdio" } });
    expect(screen.queryByLabelText("Address")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Command"), { target: { value: "npx" } });
    fireEvent.change(screen.getByLabelText("Arguments"), { target: { value: "-y\n@upstash/context7-mcp\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Add variable" }));
    fireEvent.change(screen.getByLabelText("Variable 1 name"), { target: { value: "CONTEXT7_API_KEY" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Variable 1 is secret" }));
    const value = screen.getByLabelText("Variable 1 value");
    expect(value).toBeDisabled();
    expect(value).toHaveAttribute("placeholder", "Set below after saving");
    fireEvent.click(screen.getByRole("checkbox", { name: "Safe in read-only runs" }));
    expect(screen.getByText(/‹their own›/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit).toHaveBeenCalledWith({
      name: "context7",
      description: "",
      read_only_safe: true,
      spec: {
        transport: "stdio",
        url: null,
        headers: [],
        command: { command: "npx", args: ["-y", "@upstash/context7-mcp"] },
        os_commands: {},
        env: [{ name: "CONTEXT7_API_KEY", value: "", secret: true }],
        acknowledged: [],
      },
    });
  });

  it("builds a web address MCP, with a command for one other system", async () => {
    const onSubmit = vi.fn<(body: McpBody) => Promise<void>>(async () => {});
    render(<McpForm submitLabel="Save" onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "docs" } });
    fireEvent.change(screen.getByLabelText("Address"), { target: { value: "https://mcp.example.com/mcp" } });
    fireEvent.click(screen.getByRole("button", { name: "Add header" }));
    fireEvent.change(screen.getByLabelText("Header 1 name"), { target: { value: "X-Team" } });
    fireEvent.change(screen.getByLabelText("Header 1 value"), { target: { value: "web" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      spec: { transport: "http", url: "https://mcp.example.com/mcp", headers: [{ name: "X-Team", value: "web", secret: false }], command: null },
    });
  });

  it("keeps per-system commands for a command MCP", async () => {
    const onSubmit = vi.fn<(body: McpBody) => Promise<void>>(async () => {});
    render(<McpForm submitLabel="Save" onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "stdio" } });
    fireEvent.change(screen.getByLabelText("Command"), { target: { value: "x-server" } });
    fireEvent.change(screen.getByLabelText("Windows command"), { target: { value: "x-server.exe" } });
    fireEvent.change(screen.getByLabelText("Windows arguments"), { target: { value: "--quiet" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(onSubmit.mock.calls[0][0].spec.os_commands).toEqual({ windows: { command: "x-server.exe", args: ["--quiet"] } });
  });

  it("shows the error the save throws", async () => {
    render(<McpForm submitLabel="Save" onSubmit={async () => { throw new ApiError(409, "hub_name_taken"); }} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("Address"), { target: { value: "https://x" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You already have a tool with that name.");
  });

  it("refuses a placeholder that names no secret before sending", async () => {
    const onSubmit = vi.fn<(body: McpBody) => Promise<void>>(async () => {});
    render(<McpForm submitLabel="Save" onSubmit={onSubmit} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("Address"), { target: { value: "https://x/mcp?key=${API_KEY}" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A ${…} placeholder doesn't match any secret.");
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
