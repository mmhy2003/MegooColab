import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProjectPicker, ProjectSelect } from "@/components/chats/ProjectPicker";

afterEach(cleanup);

const PROJECTS = [
  { key: "SD", name: "Sales Dashboard" },
  { key: "SLW", name: "SuperLiveWeb" },
  { key: "MK", name: "MegooKit" },
  { key: "PAY", name: "Payments" },
];
const COUNTS = new Map([["SLW", { active: 2, total: 9 }], ["MK", { active: 1, total: 3 }], ["SD", { active: 0, total: 2 }]]);

function Box({ initial = [] as string[], onChange = vi.fn() }) {
  const [value, setValue] = useState(initial);
  return (
    <ProjectPicker
      projects={PROJECTS}
      counts={COUNTS}
      value={value}
      onChange={(v) => {
        onChange(v);
        setValue(v);
      }}
    />
  );
}
const open = () => userEvent.click(screen.getByRole("combobox", { name: "Projects" }));
const option = (key: string) => screen.getByRole("option", { name: new RegExp(`^${key} `) });

describe("ProjectPicker closed", () => {
  it("reads All projects with nothing picked", () => {
    render(<Box />);
    expect(screen.getByRole("combobox", { name: "Projects" })).toHaveTextContent("All projects");
  });

  it("shows picked projects as tags, each with its own ✕", async () => {
    const onChange = vi.fn();
    render(<Box initial={["SLW", "MK"]} onChange={onChange} />);
    expect(screen.queryByText("All projects")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Remove SLW" }));
    expect(onChange).toHaveBeenLastCalledWith(["MK"]);
    expect(screen.queryByRole("button", { name: "Remove SLW" })).toBeNull();
  });

  it("past two, shows two tags and how many more", () => {
    render(<Box initial={["SLW", "MK", "SD", "PAY"]} />);
    expect(screen.getAllByRole("button", { name: /^Remove / })).toHaveLength(2);
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });
});

describe("ProjectPicker open", () => {
  it("lists every project with a checkbox, its key, name and chats, the picked ones first", async () => {
    render(<Box initial={["MK"]} />);
    await open();
    const options = screen.getAllByRole("option");
    expect(options.map((o) => o.getAttribute("data-key"))).toEqual(["MK", "SD", "SLW", "PAY"]);
    expect(option("MK")).toHaveAttribute("aria-checked", "true");
    expect(option("SD")).toHaveAttribute("aria-checked", "false");
    expect(option("SLW")).toHaveTextContent("SuperLiveWeb");
    expect(within(option("SLW")).getByTitle("2 active of 9 chats")).toHaveTextContent("2 / 9");
    expect(within(option("PAY")).getByTitle("0 active of 0 chats")).toHaveTextContent("0 / 0");
    expect(screen.getByText("1 of 4 picked")).toBeInTheDocument();
  });

  it("ticks and unticks, and stays open to pick more", async () => {
    const onChange = vi.fn();
    render(<Box onChange={onChange} />);
    await open();
    await userEvent.click(option("SLW"));
    expect(onChange).toHaveBeenLastCalledWith(["SLW"]);
    await userEvent.click(option("MK"));
    expect(onChange).toHaveBeenLastCalledWith(["SLW", "MK"]);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    await userEvent.click(option("SLW"));
    expect(onChange).toHaveBeenLastCalledWith(["MK"]);
  });

  it("searches keys and names, marks the match, and says when nothing matches", async () => {
    render(<Box />);
    await open();
    const search = screen.getByPlaceholderText("Search projects…");
    await userEvent.type(search, "sa");
    expect(screen.getAllByRole("option").map((o) => o.getAttribute("data-key"))).toEqual(["SD"]);
    expect(option("SD").querySelector("mark")).toHaveTextContent("Sa");
    await userEvent.clear(search);
    await userEvent.type(search, "pay");
    expect(screen.getAllByRole("option").map((o) => o.getAttribute("data-key"))).toEqual(["PAY"]);
    await userEvent.clear(search);
    await userEvent.type(search, "zzz");
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByText('No project matches "zzz".')).toBeInTheDocument();
  });

  it("selects all, or only what the search shows, and clears", async () => {
    const onChange = vi.fn();
    render(<Box initial={["MK"]} onChange={onChange} />);
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(onChange).toHaveBeenLastCalledWith(["MK", "SD", "SLW", "PAY"]);
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(onChange).toHaveBeenLastCalledWith([]);
    await userEvent.type(screen.getByPlaceholderText("Search projects…"), "s");
    await userEvent.click(screen.getByRole("button", { name: "Select shown" }));
    expect(onChange).toHaveBeenLastCalledWith(["SD", "SLW", "PAY"]);
  });

  it("shows projects that arrive after it opened", async () => {
    const { rerender } = render(<ProjectPicker projects={[]} counts={COUNTS} value={[]} onChange={() => {}} />);
    await open();
    expect(screen.getByText("No projects.")).toBeInTheDocument();
    rerender(<ProjectPicker projects={PROJECTS} counts={COUNTS} value={[]} onChange={() => {}} />);
    expect(screen.getAllByRole("option")).toHaveLength(4);
  });

  it("ticks the highlighted project with Enter", async () => {
    const onChange = vi.fn();
    render(<Box onChange={onChange} />);
    await open();
    await userEvent.type(screen.getByPlaceholderText("Search projects…"), "kit");
    fireEvent.keyDown(screen.getByPlaceholderText("Search projects…"), { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith(["MK"]);
  });
});

function One({ initial = "", disabled = false, onChange = vi.fn() }) {
  const [value, setValue] = useState(initial);
  return (
    <ProjectSelect
      projects={PROJECTS}
      value={value}
      disabled={disabled}
      onChange={(v) => {
        onChange(v);
        setValue(v);
      }}
    />
  );
}
const openOne = () => userEvent.click(screen.getByRole("combobox", { name: "Project" }));

describe("ProjectSelect (one project)", () => {
  it("reads Choose a project, then the picked project's key and name", () => {
    render(<One />);
    expect(screen.getByRole("combobox", { name: "Project" })).toHaveTextContent("Choose a project");
    cleanup();
    render(<One initial="SLW" />);
    expect(screen.getByRole("combobox", { name: "Project" })).toHaveTextContent("SLWSuperLiveWeb");
  });

  it("picking one ticks it and closes the list", async () => {
    const onChange = vi.fn();
    render(<One initial="SLW" onChange={onChange} />);
    await openOne();
    expect(screen.getByRole("option", { name: "SLW — SuperLiveWeb" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("option", { name: "MK — MegooKit" })).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByRole("button", { name: /Select all/ })).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: "MK — MegooKit" }));
    expect(onChange).toHaveBeenCalledWith("MK");
    expect(screen.queryByRole("option")).toBeNull();
    expect(screen.getByRole("combobox", { name: "Project" })).toHaveTextContent("MKMegooKit");
  });

  it("searches keys and names, marks the match, and says when nothing matches", async () => {
    render(<One />);
    await openOne();
    const search = screen.getByPlaceholderText("Search projects…");
    await userEvent.type(search, "pay");
    expect(screen.getAllByRole("option").map((o) => o.getAttribute("aria-label"))).toEqual(["PAY — Payments"]);
    expect(within(screen.getByRole("option")).getAllByText(/pay/i, { selector: "mark" })).toHaveLength(2);
    fireEvent.change(search, { target: { value: "zzz" } });
    expect(await screen.findByText('No project matches "zzz".')).toBeInTheDocument();
  });

  it("can't be changed when it's fixed", () => {
    render(<One initial="SLW" disabled />);
    expect(screen.getByRole("combobox", { name: "Project" })).toBeDisabled();
  });
});
