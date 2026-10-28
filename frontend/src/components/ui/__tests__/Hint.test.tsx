import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { TooltipProvider } from "@/components/shadcn/tooltip";
import { Hint } from "@/components/ui/Hint";

afterEach(cleanup);

function show() {
  render(
    <TooltipProvider delayDuration={0}>
      <Hint label="Close">
        <button type="button" aria-label="Close" className="icon-btn">x</button>
      </Hint>
    </TooltipProvider>,
  );
  return screen.getByRole("button", { name: "Close" });
}

describe("Hint", () => {
  it("names an icon button on hover", async () => {
    const button = show();
    await userEvent.hover(button);
    expect(await screen.findByRole("tooltip", { name: "Close" })).toBeInTheDocument();
  });

  it("names it on keyboard focus too, and Escape hides it", async () => {
    show();
    await userEvent.tab();
    expect(await screen.findByRole("tooltip", { name: "Close" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("keeps the button's own name, without a title", () => {
    const button = show();
    expect(button).toHaveAccessibleName("Close");
    expect(button).not.toHaveAttribute("title");
  });
});
