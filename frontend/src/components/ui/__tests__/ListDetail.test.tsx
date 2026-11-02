import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ListDetail, ListRow, pickChosen, useChosenParam } from "@/components/ui/ListDetail";

let search = "";
const push = vi.fn();
const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/settings/agents",
  useSearchParams: () => new URLSearchParams(search),
}));

beforeEach(() => {
  search = "";
  push.mockClear();
  replace.mockClear();
});
afterEach(cleanup);

const a = { id: "a" };
const b = { id: "b" };
const idOf = (t: { id: string }) => t.id;

describe("pickChosen", () => {
  it("pickChosen: a matching id is shown and chosen", () => {
    expect(pickChosen([a, b], "b", idOf)).toEqual({ shown: b, chosen: true });
  });

  it("an unknown id shows the first item and keeps the list on a phone", () => {
    expect(pickChosen([a, b], "gone", idOf)).toEqual({ shown: a, chosen: false });
    expect(pickChosen([a, b], null, idOf)).toEqual({ shown: a, chosen: false });
    expect(pickChosen([], "x", idOf)).toEqual({ shown: null, chosen: false });
  });
});

describe("useChosenParam", () => {
  it("useChosenParam pushes a chosen id and keeps the tab", () => {
    search = "tab=tools";
    const { result } = renderHook(() => useChosenParam("machine"));
    expect(result.current[0]).toBeNull();
    act(() => result.current[1]("m1"));
    expect(push).toHaveBeenCalledWith("/settings/agents?tab=tools&machine=m1", { scroll: false });
    search = "tab=tools&machine=m1";
    const again = renderHook(() => useChosenParam("machine"));
    expect(again.result.current[0]).toBe("m1");
    act(() => again.result.current[1](null));
    expect(replace).toHaveBeenCalledWith("/settings/agents?tab=tools", { scroll: false });
  });
});

describe("ListDetail", () => {
  it("ListDetail shows Back only when an item is chosen", () => {
    const onBack = vi.fn();
    const { rerender } = render(
      <ListDetail listLabel="Agents" backLabel="Agents" chosen={false} onBack={onBack} list={<p>list</p>} detail={<p>detail</p>} />,
    );
    expect(screen.queryByRole("button", { name: "‹ Agents" })).toBeNull();
    expect(screen.getByRole("navigation", { name: "Agents" })).toHaveTextContent("list");
    rerender(<ListDetail listLabel="Agents" backLabel="Agents" chosen onBack={onBack} list={<p>list</p>} detail={<p>detail</p>} />);
    fireEvent.click(screen.getByRole("button", { name: "‹ Agents" }));
    expect(onBack).toHaveBeenCalled();
  });

  it("ListRow marks the selected row", () => {
    const onClick = vi.fn();
    render(
      <ul>
        <ListRow selected title="Workstation" meta="Windows" onClick={onClick} />
        <ListRow selected={false} title="Laptop" onClick={vi.fn()} />
      </ul>,
    );
    const row = screen.getByRole("button", { name: /Workstation/ });
    expect(row).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("button", { name: /Laptop/ })).not.toHaveAttribute("aria-current");
    fireEvent.click(row);
    expect(onClick).toHaveBeenCalled();
  });
});
