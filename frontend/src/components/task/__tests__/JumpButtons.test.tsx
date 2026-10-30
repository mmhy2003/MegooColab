import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { JumpButtons } from "@/components/task/JumpButtons";

type Entry = { id: string; at: string };
const entry = (n: number): Entry => ({ id: `a${n}`, at: new Date(Date.UTC(2026, 9, 31, 10, 0, n)).toISOString() });
const entries = (count: number) => Array.from({ length: count }, (_, i) => entry(i));

// jsdom does no layout: the scroller gets a height, a content height and a scroll position the test controls
const laidOut = new WeakSet<HTMLElement>();
function fakeLayout(el: HTMLElement, layout: { scrollHeight: number; clientHeight: number }) {
  if (laidOut.has(el)) return; // the ref callback runs again on every render
  laidOut.add(el);
  let top = 0;
  Object.defineProperty(el, "clientHeight", { configurable: true, get: () => layout.clientHeight });
  Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => layout.scrollHeight });
  Object.defineProperty(el, "scrollTop", {
    configurable: true,
    get: () => top,
    set: (v: number) => {
      top = Math.max(0, Math.min(v, layout.scrollHeight - layout.clientHeight));
    },
  });
  el.scrollTo = vi.fn((opts: ScrollToOptions) => {
    el.scrollTop = opts.top ?? 0;
    el.dispatchEvent(new Event("scroll"));
  }) as unknown as typeof el.scrollTo;
}

const layout = { scrollHeight: 3000, clientHeight: 500 };

function Harness({ activity, waiting = [], loadEarlier, expectQuestion }: {
  activity: Entry[];
  waiting?: string[];
  loadEarlier?: () => Promise<boolean>;
  expectQuestion?: boolean;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  return (
    <div>
      <div
        data-testid="scroller"
        ref={(el) => {
          if (el) fakeLayout(el, layout);
          ref.current = el;
        }}
      >
        <div>
          {waiting.map((w) => (
            <div key={w} data-waiting={w}>
              <button type="button">{w}</button>
            </div>
          ))}
        </div>
      </div>
      <JumpButtons scrollRef={ref} activity={activity} loadEarlier={loadEarlier} expectQuestion={expectQuestion} />
    </div>
  );
}

const scroller = () => screen.getByTestId("scroller");
function userScrollsTo(top: number) {
  act(() => {
    scroller().scrollTop = top;
    fireEvent.scroll(scroller());
  });
}

describe("JumpButtons", () => {
  it("offers Back to top only away from the top, and scrolls there", () => {
    layout.scrollHeight = 3000;
    render(<Harness activity={entries(3)} />);
    expect(screen.queryByRole("button", { name: "Back to top" })).toBeNull();

    userScrollsTo(1200);
    fireEvent.click(screen.getByRole("button", { name: "Back to top" }));
    expect(scroller().scrollTo).toHaveBeenLastCalledWith(expect.objectContaining({ top: 0 }));
  });

  it("goes to the latest and keeps following new activity", () => {
    layout.scrollHeight = 3000;
    const { rerender } = render(<Harness activity={entries(3)} />);
    expect(screen.queryByText("Following live")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Go to the latest and follow" }));
    expect(scroller().scrollTop).toBe(2500);
    expect(screen.getByText("Following live")).toBeInTheDocument();

    layout.scrollHeight = 3400; // the agent's new entry made the page longer
    rerender(<Harness activity={entries(4)} />);
    expect(scroller().scrollTop).toBe(2900);
    expect(screen.getByText("Following live")).toBeInTheDocument();
  });

  it("stops following when the person scrolls up, and counts what arrives meanwhile", () => {
    layout.scrollHeight = 3000;
    const { rerender } = render(<Harness activity={entries(3)} />);
    fireEvent.click(screen.getByRole("button", { name: "Go to the latest and follow" }));

    userScrollsTo(1800);
    expect(screen.queryByText("Following live")).toBeNull();

    layout.scrollHeight = 3400;
    rerender(<Harness activity={entries(5)} />);
    expect(scroller().scrollTop).toBe(1800); // the page stays where they are reading
    expect(screen.getByRole("button", { name: "Go to the latest and follow (2 new)" })).toBeInTheDocument();
  });

  it("follows again once the person scrolls back to the very bottom", () => {
    layout.scrollHeight = 3000;
    const { rerender } = render(<Harness activity={entries(3)} />);
    fireEvent.click(screen.getByRole("button", { name: "Go to the latest and follow" }));
    userScrollsTo(1800);
    rerender(<Harness activity={entries(4)} />);

    userScrollsTo(2500);
    expect(screen.getByText("Following live")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /new\)/ })).toBeNull();
  });

  it("keeps following when the page gets shorter under it", () => {
    layout.scrollHeight = 3000;
    render(<Harness activity={entries(3)} />);
    fireEvent.click(screen.getByRole("button", { name: "Go to the latest and follow" }));

    layout.scrollHeight = 2600; // something above collapsed: the browser moves the position up by itself
    userScrollsTo(2100);
    expect(screen.getByText("Following live")).toBeInTheDocument();
  });

  it("counts what waits on the person, jumps to each in turn and highlights it", () => {
    layout.scrollHeight = 3000;
    render(<Harness activity={entries(3)} waiting={["plan", "question"]} />);
    const jump = screen.getByRole("button", { name: "2 waiting on you" });

    fireEvent.click(jump);
    const plan = screen.getByRole("button", { name: "plan" }).parentElement!;
    const question = screen.getByRole("button", { name: "question" }).parentElement!;
    expect(plan).toHaveClass("jump-flash");
    expect(plan).toHaveFocus(); // the item itself: Tab goes on to its own buttons

    fireEvent.click(jump);
    expect(question).toHaveFocus();
    expect(question).toHaveClass("jump-flash");

    fireEvent.click(jump);
    expect(plan).toHaveFocus(); // round again
  });

  it("jumping to a waiting item stops following", () => {
    layout.scrollHeight = 3000;
    render(<Harness activity={entries(3)} waiting={["plan"]} />);
    fireEvent.click(screen.getByRole("button", { name: "Go to the latest and follow" }));
    fireEvent.click(screen.getByRole("button", { name: "1 waiting on you" }));
    expect(screen.queryByText("Following live")).toBeNull();
  });

  it("hides the waiting button at zero and updates as items are decided", async () => {
    layout.scrollHeight = 3000;
    const { rerender } = render(<Harness activity={entries(3)} waiting={["plan", "question"]} />);
    rerender(<Harness activity={entries(3)} waiting={["question"]} />);
    expect(await screen.findByRole("button", { name: "1 waiting on you" })).toBeInTheDocument();
    rerender(<Harness activity={entries(3)} waiting={[]} />);
    await waitFor(() => expect(screen.queryByRole("button", { name: /waiting on you/ })).toBeNull());
  });

  it("finds an open agent question older than the loaded activity", async () => {
    layout.scrollHeight = 3000;
    function Older() {
      const [loaded, setLoaded] = useState(0);
      const loadEarlier = vi.fn(async () => {
        setLoaded((n) => n + 1);
        return true;
      });
      return (
        <Harness
          activity={entries(3)}
          waiting={loaded >= 2 ? ["question"] : []}
          loadEarlier={loadEarlier}
          expectQuestion
        />
      );
    }
    render(<Older />);
    fireEvent.click(screen.getByRole("button", { name: "1 waiting on you" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "question" }).parentElement).toHaveFocus());
    expect(screen.getByRole("button", { name: "1 waiting on you" })).toBeInTheDocument(); // counted once
  });
});
