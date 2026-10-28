import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Brand } from "@/components/Brand";

describe("Brand", () => {
  it("shows the logo beside the name", () => {
    const { container } = render(<Brand />);
    const logo = container.querySelector("img");
    expect(logo).not.toBeNull();
    expect(decodeURIComponent(logo!.getAttribute("src") ?? "")).toContain("/logo.png");
    expect(logo).toHaveAttribute("width", "32");
    expect(logo).toHaveAttribute("alt", ""); // the name beside it says it
    expect(screen.getByText("MEGOO")).toBeInTheDocument();
  });

  it("takes a logo size and stacks the logo above the name", () => {
    const { container } = render(<Brand logoSize={72} stacked />);
    expect(container.querySelector("img")).toHaveAttribute("width", "72");
    expect(container.firstElementChild).toHaveClass("flex-col");
  });
});
