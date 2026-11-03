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

const fade = (container: HTMLElement, side: "start" | "end") => container.querySelector(`[data-fade="${side}"]`) as HTMLElement;

describe("ScrollX", () => {
  it("shows the end fade while more is hidden, and the start fade once scrolled", () => {
    const { container } = render(<ScrollX label="Wide">wide content</ScrollX>);
    const box = screen.getByLabelText("Wide");
    size(box, { scrollWidth: 500, clientWidth: 280 });
    expect(fade(container, "end")).not.toHaveClass("hidden");
    expect(fade(container, "start")).toHaveClass("hidden");
    size(box, { scrollWidth: 500, clientWidth: 280, scrollLeft: 220 });
    expect(fade(container, "start")).not.toHaveClass("hidden");
    expect(fade(container, "end")).toHaveClass("hidden");
  });

  it("no fade when it all fits", () => {
    const { container } = render(<ScrollX label="Wide">fits</ScrollX>);
    size(screen.getByLabelText("Wide"), { scrollWidth: 280, clientWidth: 280 });
    expect(fade(container, "start")).toHaveClass("hidden");
    expect(fade(container, "end")).toHaveClass("hidden");
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
