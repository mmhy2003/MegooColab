import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Surface } from "@/components/a2ui/Surface";
import { CATALOG_ID } from "@/components/a2ui/catalog";
import type { FormValues, SurfaceMessage } from "@/lib/types";

type Form = { components: Record<string, unknown>[]; data?: FormValues };
const fixtures = JSON.parse(
  readFileSync(join(process.cwd(), "..", "backend", "tests", "a2ui", "fixtures", "forms.json"), "utf8"),
) as { valid: { name: string; form: Form }[] };

/** The stored message for a form, as backend/app/a2ui/service.py's wrap builds it. */
function wrap({ components, data }: Form, surfaceId = "form-0123456789ab"): SurfaceMessage {
  return { version: "1.0", createSurface: { surfaceId, catalogId: CATALOG_ID, components, dataModel: data ?? {} } };
}

const everyInput = fixtures.valid.find((f) => f.name === "every-input")!.form;
const INPUTS = ["TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput"];

const message: SurfaceMessage = {
  version: "1.0",
  createSurface: {
    surfaceId: "form-0123456789ab",
    catalogId: CATALOG_ID,
    components: [
      { id: "root", component: "Column", children: ["intro", "name"] },
      { id: "intro", component: "Text", text: "A few details about the release." },
      {
        id: "name",
        component: "TextField",
        label: "Name",
        value: { "@path": "/name" },
        "@checks": [{ condition: { "@call": "required", args: { value: { "@path": "/name" } } }, message: "A name is needed" }],
      },
    ],
    dataModel: { name: "" },
  },
};

describe("Surface", () => {
  it("draws the form with MegooColab's own components", async () => {
    const { container } = render(<Surface message={message} />);
    expect(await screen.findByText("A few details about the release.")).toBeInTheDocument();
    expect(await screen.findByLabelText("Name")).toBeInTheDocument();
    // the renderer hosts each of our components in an <a2ui-react-…> element: never a basic catalog element
    const custom = [...container.querySelectorAll("*")].map((e) => e.localName).filter((n) => n.includes("-"));
    expect(custom.filter((n) => !n.startsWith("a2ui-react-"))).toEqual([]);
  });

  it("reports the data model and whether every check passes", async () => {
    const onChange = vi.fn();
    render(<Surface message={message} onChange={onChange} />);
    const input = await screen.findByLabelText("Name");
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ name: "" }, false));
    await userEvent.type(input, "x");
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ name: "x" }, true));
  });

  it("shows the check message once the field was changed back to empty", async () => {
    render(<Surface message={message} />);
    const input = await screen.findByLabelText("Name");
    expect(screen.queryByText("A name is needed")).not.toBeInTheDocument();
    await userEvent.type(input, "x");
    await userEvent.clear(input);
    expect(await screen.findByText("A name is needed")).toBeInTheDocument();
  });

  it("draws every valid fixture form", async () => {
    for (const { name, form } of fixtures.valid) {
      const { unmount } = render(<Surface message={wrap(form)} />);
      for (const c of form.components.filter((c) => INPUTS.includes(String(c.component)))) {
        const label = String(c.label);
        const found =
          c.component === "ChoicePicker"
            ? await screen.findByRole("group", { name: label })
            : await screen.findByLabelText(label);
        expect(found, `${name}: ${label}`).toBeVisible();
      }
      unmount();
    }
  });

  it("reports data and validity", async () => {
    const onChange = vi.fn();
    render(<Surface message={wrap(everyInput)} onChange={onChange} />);
    await userEvent.type(await screen.findByLabelText("Email"), "ops@example.com");
    const tag = screen.getByLabelText("Tag");
    await userEvent.type(tag, "x12");
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ tag: "x12" }), false));
    expect(await screen.findByText("Like v12")).toBeInTheDocument();

    await userEvent.clear(tag);
    await userEvent.type(tag, "v12");
    await userEvent.click(screen.getByLabelText("Share the logs"));
    await userEvent.click(screen.getByRole("radio", { name: "America" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "API" }));
    fireEvent.change(screen.getByLabelText("Traffic (%)"), { target: { value: "40" } });
    fireEvent.change(screen.getByLabelText("Start"), { target: { value: "2026-12-01T09:30" } });
    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith(
        {
          ...everyInput.data,
          email: "ops@example.com",
          tag: "v12",
          share: true,
          region: ["us"],
          targets: ["api"],
          load: 40,
          when: "2026-12-01T09:30",
        },
        true,
      ),
    );
    expect(screen.queryByText("Like v12")).not.toBeInTheDocument();
  });

  it("readOnly disables every input", async () => {
    const onChange = vi.fn();
    const { container } = render(<Surface message={wrap(everyInput)} readOnly onChange={onChange} />);
    await screen.findByLabelText("Email");
    const fields = [...container.querySelectorAll("input, textarea, select, button")];
    // 4 text fields, the checkbox, 2 + 3 options, the slider and the date-time
    expect(fields).toHaveLength(12);
    for (const field of fields) expect(field).toBeDisabled();
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith(everyInput.data, false));
  });

  it("draws a chips ChoicePicker as buttons that toggle", async () => {
    const onChange = vi.fn();
    const form: Form = {
      components: [
        { id: "root", component: "Column", children: ["envs"] },
        {
          id: "envs",
          component: "ChoicePicker",
          label: "Environments",
          variant: "multipleSelection",
          displayStyle: "chips",
          options: [{ label: "Staging", value: "staging" }, { label: "Production", value: "prod" }],
          value: { "@path": "/envs" },
        },
      ],
      data: { envs: ["staging"] },
    };
    render(<Surface message={wrap(form)} onChange={onChange} />);
    const prod = await screen.findByRole("button", { name: "Production" });
    expect(screen.getByRole("button", { name: "Staging" })).toHaveAttribute("aria-pressed", "true");
    expect(prod).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(prod);
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ envs: ["staging", "prod"] }, true));
  });

  it("Text renders markdown and keeps remote images as links", async () => {
    const form: Form = {
      components: [
        { id: "root", component: "Column", children: ["intro", "ok"] },
        { id: "intro", component: "Text", text: "**Read this** ![the plan](https://example.com/plan.png)" },
        { id: "ok", component: "CheckBox", label: "Go ahead?", value: { "@path": "/ok" } },
      ],
    };
    const { container } = render(<Surface message={wrap(form)} />);
    expect((await screen.findByText("Read this")).tagName).toBe("STRONG");
    expect(screen.getByRole("link", { name: "the plan" })).toHaveAttribute("href", "https://example.com/plan.png");
    expect(container.querySelector("img")).toBeNull();
  });
});

const cardFixtures = JSON.parse(
  readFileSync(join(process.cwd(), "..", "backend", "tests", "a2ui", "fixtures", "cards.json"), "utf8"),
) as { valid: { name: string; card: Form }[] };
const exampleCard = cardFixtures.valid.find((f) => f.name === "example")!.card;
const asCard = (card: Form) => wrap(card, "card-0123456789ab");

describe("Surface drawing a card", () => {
  it("draws every valid card fixture", async () => {
    for (const { name, card } of cardFixtures.valid) {
      const { container, unmount } = render(<Surface message={asCard(card)} readOnly />);
      // drawn (or failed, which the alert check below catches)
      await waitFor(() => expect(container).not.toBeEmptyDOMElement());
      for (const c of card.components.filter((c) => c.component === "StatTile")) {
        const tile = await screen.findByRole("group", { name: String(c.label) });
        expect(tile, `${name}: ${String(c.label)}`).toHaveTextContent(String(c.value));
      }
      expect(screen.queryByRole("alert"), name).not.toBeInTheDocument();
      const custom = [...container.querySelectorAll("*")].map((e) => e.localName).filter((n) => n.includes("-"));
      expect(custom.filter((n) => !n.startsWith("a2ui-react-")), name).toEqual([]);
      unmount();
    }
  });

  it("a StatTile is coloured by its tone", async () => {
    render(<Surface message={asCard(exampleCard)} readOnly />);
    const tile = await screen.findByRole("group", { name: "Failed" });
    expect(tile).toHaveAttribute("data-tone", "bad");
    expect(within(tile).getByText("3")).toHaveClass("text-pink");
  });

  it("switches tabs", async () => {
    render(<Surface message={asCard(exampleCard)} readOnly />);
    const failing = await screen.findByRole("tab", { name: "Failing" });
    const notes = screen.getByRole("tab", { name: "Notes" });
    expect(failing).toHaveAttribute("aria-selected", "true");
    const flaky = screen.getByText("flaky", { exact: false });
    expect(flaky).not.toBeVisible();
    await userEvent.click(notes);
    expect(flaky).toBeVisible();
    expect(notes).toHaveAttribute("aria-selected", "true");
    expect(failing).toHaveAttribute("aria-selected", "false");
    await userEvent.keyboard("{ArrowLeft}");
    expect(failing).toHaveAttribute("aria-selected", "true");
    expect(flaky).not.toBeVisible();
    // both panels stay mounted
    expect(screen.getAllByRole("tabpanel", { hidden: true })).toHaveLength(2);
  });

  it("expands a template list", async () => {
    render(<Surface message={asCard(exampleCard)} readOnly />);
    const rows = await screen.findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    const link = screen.getByRole("link", { name: "MC-181" });
    expect(link).toHaveAttribute("href", "/projects/MC/board?task=MC-181");
    expect(rows[0]).toHaveTextContent("Login times out");
  });

  it("a TaskLink that isn't a task key is plain text", async () => {
    const card: Form = {
      components: [{ id: "root", component: "TaskLink", task: { "@path": "/key" }, label: "Odd" }],
      data: { key: "not-a-key" },
    };
    render(<Surface message={asCard(card)} readOnly />);
    expect(await screen.findByText("not-a-key Odd")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("a long List scrolls inside the card", async () => {
    render(<Surface message={asCard(exampleCard)} readOnly />);
    const list = await screen.findByRole("list");
    expect(list).toHaveClass("max-h-60", "overflow-y-auto");
  });
});

const panelFixtures = JSON.parse(
  readFileSync(join(process.cwd(), "..", "backend", "tests", "a2ui", "fixtures", "panels.json"), "utf8"),
) as { valid: { name: string; panel: Form }[] };
const examplePanel = panelFixtures.valid.find((f) => f.name === "example")!.panel;
const asPanel = (panel: Form) => wrap(panel, "panel-0123456789ab");

describe("Surface drawing a panel", () => {
  it("draws every valid panel fixture", async () => {
    for (const { name, panel } of panelFixtures.valid) {
      const { container, unmount } = render(<Surface message={asPanel(panel)} readOnly />);
      await waitFor(() => expect(container).not.toBeEmptyDOMElement());
      for (const c of panel.components.filter((c) => c.component === "StatTile")) {
        const tile = await screen.findByRole("group", { name: String(c.label) });
        expect(tile, `${name}: ${String(c.label)}`).toHaveTextContent(String(c.value));
      }
      for (const c of panel.components.filter((c) => c.component === "Chart")) {
        await waitFor(() => expect(screen.getByRole("region", { name: String(c.title) }), name).toBeInTheDocument());
      }
      expect(screen.queryByRole("alert"), name).not.toBeInTheDocument();
      const custom = [...container.querySelectorAll("*")].map((e) => e.localName).filter((n) => n.includes("-"));
      expect(custom.filter((n) => !n.startsWith("a2ui-react-")), name).toEqual([]);
      unmount();
    }
  });

  it("a chart's table view lists its points", async () => {
    render(<Surface message={asPanel(examplePanel)} readOnly />);
    const chart = await screen.findByRole("region", { name: "Slowest suites" });
    await userEvent.click(within(chart).getByRole("button", { name: "Show table" }));
    const rows = within(chart).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("api131");
  });
});

describe("Surface when the renderer fails", () => {
  const failure = "This form couldn't be shown. You can still answer in your own words.";

  afterEach(() => {
    vi.doUnmock("@a2ui/react");
    vi.doUnmock("@/components/a2ui/Chart");
    vi.resetModules();
    vi.restoreAllMocks();
  });

  it("shows the failure message when the renderer can't load", async () => {
    vi.resetModules();
    vi.doMock("@a2ui/react", () => {
      throw new Error("chunk failed to load");
    });
    const { Surface } = await import("@/components/a2ui/Surface");
    const onChange = vi.fn();
    render(<Surface message={message} onChange={onChange} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(failure);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows the failure message when the renderer throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.resetModules();
    vi.doMock("@a2ui/react", async (original) => ({
      ...(await original<typeof import("@a2ui/react")>()),
      A2uiSurface: () => {
        throw new Error("broken surface");
      },
    }));
    const { Surface } = await import("@/components/a2ui/Surface");
    const onChange = vi.fn();
    render(<Surface message={message} onChange={onChange} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(failure);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows the fallback when the renderer can't load", async () => {
    vi.resetModules();
    vi.doMock("@a2ui/react", () => {
      throw new Error("chunk failed to load");
    });
    const { Surface } = await import("@/components/a2ui/Surface");
    render(<Surface message={message} fallback={<p role="alert">Card text</p>} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Card text");
    expect(alert).not.toHaveTextContent(failure);
  });

  it("shows the fallback when the renderer throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.resetModules();
    vi.doMock("@a2ui/react", async (original) => ({
      ...(await original<typeof import("@a2ui/react")>()),
      A2uiSurface: () => {
        throw new Error("broken surface");
      },
    }));
    const { Surface } = await import("@/components/a2ui/Surface");
    render(<Surface message={message} fallback={<p role="alert">Card text</p>} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Card text");
    expect(alert).not.toHaveTextContent(failure);
  });

  it("shows the fallback when the chart can't load", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.resetModules();
    vi.doMock("@/components/a2ui/Chart", () => {
      throw new Error("chunk failed");
    });
    const { Surface } = await import("@/components/a2ui/Surface");
    render(<Surface message={asPanel(examplePanel)} readOnly fallback={<p role="alert">Panel text</p>} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Panel text");
  });
});
