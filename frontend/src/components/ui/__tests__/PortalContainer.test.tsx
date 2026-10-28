import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/shadcn/popover";
import { Dialog } from "@/components/ui/Dialog";

afterEach(cleanup);

function popover() {
  return (
    <Popover open>
      <PopoverTrigger>t</PopoverTrigger>
      <PopoverContent aria-label="P">x</PopoverContent>
    </Popover>
  );
}

describe("PortalContainer", () => {
  it("renders a popup inside an open dialog, which sits above the page (test_portal_follows_the_dialog)", () => {
    render(
      <Dialog open title="T" onClose={() => {}}>
        {popover()}
      </Dialog>,
    );
    expect(screen.getByRole("dialog", { name: "T" })).toContainElement(screen.getByRole("dialog", { name: "P" }));
  });

  it("renders it under the body elsewhere", () => {
    const { container } = render(popover());
    const content = screen.getByRole("dialog", { name: "P" });
    expect(container).not.toContainElement(content);
    expect(document.body).toContainElement(content);
  });
});
