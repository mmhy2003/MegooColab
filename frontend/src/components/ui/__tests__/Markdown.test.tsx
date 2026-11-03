import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "@/components/ui/Markdown";

describe("Markdown", () => {
  it("wraps long words anywhere and marks code blocks and tables as sideways scrollers", () => {
    const { container } = render(
      <Markdown>{"Text\n\n```ts\nconst x = 1;\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |"}</Markdown>,
    );
    expect(container.firstElementChild).toHaveClass("wrap-anywhere");
    expect(container.querySelector("pre")).toHaveAttribute("data-scroll-x");
    expect(container.querySelector("table")!.closest("[data-scroll-x]")).not.toBeNull();
    // a cell breaks a long word only when it must: anywhere would squeeze a wide table to the box instead of letting
    // it scroll (overflow-wrap anywhere lowers the cells' minimum width)
    expect(container.querySelector("table")).toHaveClass("wrap-break-word");
  });

  it("renders a remote image as a plain link, never loading it", () => {
    const { container } = render(<Markdown>{"![diagram](https://evil.example/x.png)"}</Markdown>);
    expect(container.querySelector("img")).toBeNull();
    const link = screen.getByRole("link", { name: "diagram" });
    expect(link).toHaveAttribute("href", "https://evil.example/x.png");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("falls back to the address when the image has no alt text", () => {
    render(<Markdown>{"![](https://evil.example/x.png)"}</Markdown>);
    expect(screen.getByRole("link", { name: "https://evil.example/x.png" })).toBeInTheDocument();
  });

  it("still renders data: images inline", () => {
    const src = "data:image/png;base64,iVBORw0KGgo=";
    const { container } = render(<Markdown>{`![dot](${src})`}</Markdown>);
    expect(container.querySelector("img")).toHaveAttribute("src", src);
  });

  it("renders a mention as text, never a user: link", () => {
    const { container } = render(
      <Markdown>{"Hi @[Sara Kim](user:0b5c2f9e-3f1a-4c55-9d1e-2a8f7c6b5d4e), and [x](user:0b5c2f9e-3f1a-4c55-9d1e-2a8f7c6b5d4e)"}</Markdown>,
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toBe("Hi @Sara Kim, and x");
    expect(screen.getByText("@Sara Kim").tagName).toBe("SPAN");
  });

  it("renders the task agent's mention as text too", () => {
    const { container } = render(<Markdown>{"@[laptop-claude](agent:0b5c2f9e-3f1a-4c55-9d1e-2a8f7c6b5d4e) use X"}</Markdown>);
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toBe("@laptop-claude use X");
  });
});
