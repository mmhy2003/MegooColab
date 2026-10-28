import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Backdrop } from "@/components/ui/Backdrop";

afterEach(cleanup);

describe("Backdrop", () => {
  it("covers the page with a blur, outside the component that opened it", () => {
    const { container } = render(<Backdrop onClose={() => {}} />);
    const backdrop = document.querySelector("[data-backdrop]");
    expect(backdrop).not.toBeNull();
    expect(container.contains(backdrop)).toBe(false); // portalled to <body>: the header's own blur would trap it
    expect(backdrop!.className).toMatch(/backdrop-blur/);
  });

  it("closes on a click and on Escape", () => {
    const onClose = vi.fn();
    render(<Backdrop onClose={onClose} />);
    fireEvent.click(document.querySelector("[data-backdrop]")!);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
