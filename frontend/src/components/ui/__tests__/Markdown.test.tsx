import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "@/components/ui/Markdown";

describe("Markdown", () => {
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
});
