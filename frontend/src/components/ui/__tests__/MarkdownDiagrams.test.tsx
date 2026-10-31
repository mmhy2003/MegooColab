import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Markdown } from "@/components/ui/Markdown";
import { MAX_DIAGRAM_CHARS } from "@/lib/mermaid";

// jsdom cannot lay out SVG, so the library itself is replaced; what is checked is what Markdown asks of it
const mermaid = vi.hoisted(() => ({
  initialize: vi.fn(),
  parse: vi.fn(async () => ({ diagramType: "sequence" })),
  render: vi.fn(async (id: string) => ({ svg: `<svg data-testid="drawn" id="${id}"></svg>` })),
}));
vi.mock("mermaid", () => ({ default: mermaid }));

const SEQUENCE = "sequenceDiagram\n    V->>P: Scan QR code";

beforeEach(() => {
  mermaid.initialize.mockClear();
  mermaid.parse.mockClear();
  mermaid.render.mockClear();
});
afterEach(() => {
  delete document.documentElement.dataset.theme;
});

describe("Markdown tables", () => {
  it("puts a table in a box that scrolls sideways", () => {
    const { container } = render(<Markdown>{"| Topic | Decision |\n| --- | --- |\n| Scope | Full chat |"}</Markdown>);
    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(table!.parentElement).toHaveClass("overflow-x-auto");
    expect(screen.getByRole("columnheader", { name: "Topic" })).toBeInTheDocument();
  });
});

describe("Markdown diagrams", () => {
  it("draws a mermaid block as a diagram, in strict mode", async () => {
    render(<Markdown>{"```mermaid\n" + SEQUENCE + "\n```"}</Markdown>);
    expect(await screen.findByTestId("drawn")).toBeInTheDocument();
    expect(mermaid.render).toHaveBeenCalledWith(expect.any(String), SEQUENCE);
    expect(mermaid.initialize).toHaveBeenCalledWith(
      expect.objectContaining({ startOnLoad: false, securityLevel: "strict" }),
    );
    expect(screen.queryByText(/sequenceDiagram/)).toBeNull();
  });

  it("fits a diagram to its box but never shrinks it past reading: a narrow screen scrolls instead", async () => {
    mermaid.render.mockResolvedValueOnce({
      svg: '<svg data-testid="drawn" width="100%" style="max-width: 1250.5px;" viewBox="0 0 1250.5 400"></svg>',
    });
    render(<Markdown>{"```mermaid\n" + SEQUENCE + "\n```"}</Markdown>);
    const svg = await screen.findByTestId("drawn");
    expect(svg.getAttribute("style")).toBe("max-width: 1250.5px; min-width: min(1250.5px, 40rem);");
    expect(svg.parentElement).toHaveClass("overflow-x-auto");
  });

  it("follows the dark theme", async () => {
    document.documentElement.dataset.theme = "dark";
    render(<Markdown>{"```mermaid\n" + SEQUENCE + "\n```"}</Markdown>);
    await screen.findByTestId("drawn");
    expect(mermaid.initialize).toHaveBeenLastCalledWith(expect.objectContaining({ theme: "dark" }));
  });

  it("switches between the drawing and its code", async () => {
    const user = userEvent.setup();
    render(<Markdown>{"```mermaid\n" + SEQUENCE + "\n```"}</Markdown>);
    await screen.findByTestId("drawn");
    expect(screen.getByRole("button", { name: "Diagram" })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "Code" }));
    expect(screen.getByText(/V->>P: Scan QR code/).closest("pre")).not.toBeNull();
    expect(screen.queryByTestId("drawn")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Diagram" }));
    expect(screen.getByTestId("drawn")).toBeInTheDocument();
  });

  it("draws a diagram quoted inside another code block, keeping the text around it as code", async () => {
    const quoted = "````markdown\n## 7.6 Flow\n\n```mermaid\ngraph TD\n  A-->B\n```\n\nThe end.\n````";
    render(<Markdown>{quoted}</Markdown>);
    expect(await screen.findByTestId("drawn")).toBeInTheDocument();
    expect(mermaid.render).toHaveBeenCalledWith(expect.any(String), "graph TD\n  A-->B");
    expect(screen.getByText("## 7.6 Flow").closest("pre")).not.toBeNull();
    expect(screen.getByText("The end.").closest("pre")).not.toBeNull();
  });

  it("draws a quoted diagram whose fence is indented", async () => {
    render(<Markdown>{"````\n  ```mermaid\n  graph TD\n    A-->B\n  ```\n````"}</Markdown>);
    await screen.findByTestId("drawn");
    expect(mermaid.render).toHaveBeenCalledWith(expect.any(String), "graph TD\n  A-->B");
  });

  it("keeps a quoted mermaid fence that never closes as code", () => {
    render(<Markdown>{"````\n```mermaid\ngraph TD\n  A-->B\n````"}</Markdown>);
    expect(screen.getByText(/```mermaid/).closest("pre")).not.toBeNull();
    expect(mermaid.render).not.toHaveBeenCalled();
  });

  it("shows the code and the reason when a diagram has a mistake", async () => {
    mermaid.parse.mockRejectedValueOnce(new Error("Parse error on line 4:\n...V-x->B\n----^"));
    render(<Markdown>{"```mermaid\nsequenceDiagram\n  V-x->B: Scan\n```"}</Markdown>);
    expect(await screen.findByText(/couldn.t be drawn: Parse error on line 4:$/)).toBeInTheDocument();
    expect(screen.getByText(/V-x->B: Scan/).closest("pre")).not.toBeNull();
    expect(mermaid.render).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Code" })).toBeNull();
  });

  it("shows a very large diagram as code without drawing it", () => {
    const big = "graph TD\n" + "  A-->B\n".repeat(Math.ceil(MAX_DIAGRAM_CHARS / 8));
    render(<Markdown>{"```mermaid\n" + big + "```"}</Markdown>);
    expect(screen.getByText(/too large to draw/)).toBeInTheDocument();
    expect(mermaid.parse).not.toHaveBeenCalled();
    expect(mermaid.render).not.toHaveBeenCalled();
  });

  it("leaves other code blocks alone", async () => {
    const { container } = render(<Markdown>{"```js\nconst mermaid = 1;\n```"}</Markdown>);
    expect(container.querySelector("pre code.language-js")).toHaveTextContent("const mermaid = 1;");
    await waitFor(() => expect(mermaid.render).not.toHaveBeenCalled());
  });
});
