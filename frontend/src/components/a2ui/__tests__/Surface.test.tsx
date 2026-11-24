import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

describe("Surface when the renderer fails", () => {
  const failure = "This form couldn't be shown. You can still answer in your own words.";

  afterEach(() => {
    vi.doUnmock("@a2ui/react");
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
});
