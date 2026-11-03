import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ScrollX } from "@/components/ui/ScrollX";

afterEach(cleanup);

/** jsdom has no layout: give the scroller its sizes, then tell it it scrolled. */
function size(el: HTMLElement, { scrollWidth, clientWidth, scrollLeft = 0 }: { scrollWidth: number; clientWidth: number; scrollLeft?: number }) {
  Object.defineProperty(el, "scrollWidth", { configurable: true, value: scrollWidth });
  Object.defineProperty(el, "clientWidth", { configurable: true, value: clientWidth });
  el.scrollLeft = scrollLeft;
  fireEvent.scroll(el);
}

// the edges with more to see; the fade is a mask on the scroller, so it shows whatever is behind (the page's grid)
const more = (el: HTMLElement) => el.getAttribute("data-more");

describe("ScrollX", () => {
  it("fades the end while more is hidden, and the start once scrolled", () => {
    render(<ScrollX label="Wide">wide content</ScrollX>);
    const box = screen.getByLabelText("Wide");
    size(box, { scrollWidth: 500, clientWidth: 280 });
    expect(more(box)).toBe("end");
    expect(box.style.maskImage).toContain("transparent 100%");
    size(box, { scrollWidth: 500, clientWidth: 280, scrollLeft: 110 });
    expect(more(box)).toBe("both");
    size(box, { scrollWidth: 500, clientWidth: 280, scrollLeft: 220 });
    expect(more(box)).toBe("start");
    expect(box.style.maskImage).toContain("transparent 0");
  });

  it("no fade when it all fits", () => {
    render(<ScrollX label="Wide">fits</ScrollX>);
    const box = screen.getByLabelText("Wide");
    size(box, { scrollWidth: 280, clientWidth: 280 });
    expect(more(box)).toBeNull();
    expect(box.style.maskImage).toBe("");
  });

  it("a tab bar also shows › while more tabs hide", () => {
    const { container } = render(<ScrollX label="Tabs" chevron>tabs</ScrollX>);
    const box = screen.getByLabelText("Tabs");
    const chevron = () => container.querySelector("[data-chevron]");
    size(box, { scrollWidth: 500, clientWidth: 280 });
    expect(chevron()).not.toBeNull();
    expect(chevron()).toHaveAttribute("aria-hidden", "true");
    size(box, { scrollWidth: 500, clientWidth: 280, scrollLeft: 220 });
    expect(chevron()).toBeNull();
  });

  it("marks its scroller with data-scroll-x and the given label", () => {
    render(<ScrollX label="Wide">x</ScrollX>);
    expect(screen.getByLabelText("Wide")).toHaveAttribute("data-scroll-x");
  });

  it("contains positioned content, so a screen-reader label far along can't widen the page", () => {
    // an absolutely placed child's box is its nearest positioned ancestor: the scroller itself must be one, or the
    // child escapes the scroller's clipping (the board's column labels did, widening a phone's page to 1006 px)
    render(<ScrollX label="Wide">x</ScrollX>);
    expect(screen.getByLabelText("Wide")).toHaveClass("relative");
  });

  it("can be a nav landmark", () => {
    render(<ScrollX as="nav" label="Project">x</ScrollX>);
    expect(screen.getByRole("navigation", { name: "Project" })).toHaveAttribute("data-scroll-x");
  });
});
