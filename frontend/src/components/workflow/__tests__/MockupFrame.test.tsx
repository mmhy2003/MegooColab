import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MockupFrame } from "@/components/workflow/MockupFrame";

afterEach(cleanup);

function setup() {
  const onChoice = vi.fn();
  render(<MockupFrame mockupId="m1" version={2} title="Login" choices={["a", "b"]} onChoice={onChoice} />);
  const frame = screen.getByTitle("Mockup v2: Login") as HTMLIFrameElement;
  const send = (init: { source?: MessageEventSource | null; origin?: string; data?: unknown }) =>
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          source: "source" in init ? init.source : frame.contentWindow,
          origin: init.origin ?? "null",
          data: "data" in init ? init.data : { type: "megoo-choice", choice: "a" },
        }),
      );
    });
  return { frame, onChoice, send };
}

describe("MockupFrame", () => {
  it("iframe has sandbox allow-scripts only", () => {
    const { frame } = setup();
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("src")).toBe("/api/mockups/m1/view");
    const link = screen.getByRole("link", { name: /Open full screen/ });
    expect(link).toHaveAttribute("href", "/api/mockups/m1/view");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("accepts a declared choice from its own frame with the opaque origin", () => {
    const { onChoice, send } = setup();
    send({});
    expect(onChoice).toHaveBeenCalledExactlyOnceWith("a");
  });

  it("ignores messages from other sources, non-null origins, wrong types and undeclared choices", () => {
    const { onChoice, send } = setup();
    send({ source: window }); // another window
    send({ source: null });
    send({ origin: "https://evil.example" });
    send({ origin: window.location.origin });
    send({ data: { type: "megoo-choice", choice: "zzz" } }); // not declared
    send({ data: { type: "other", choice: "a" } });
    send({ data: { type: "megoo-choice", choice: 1 } });
    send({ data: { type: "megoo-choice" } });
    send({ data: "megoo-choice" });
    send({ data: null });
    expect(onChoice).not.toHaveBeenCalled();
  });
});
