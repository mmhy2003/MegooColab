import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FormSurface } from "@/components/a2ui/FormSurface";
import { CATALOG_ID } from "@/components/a2ui/catalog";
import type { FormMessage } from "@/lib/types";

const message: FormMessage = {
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

describe("FormSurface", () => {
  it("draws the form with MegooColab's own components", async () => {
    const { container } = render(<FormSurface message={message} />);
    expect(await screen.findByText("A few details about the release.")).toBeInTheDocument();
    expect(await screen.findByLabelText("Name")).toBeInTheDocument();
    // the renderer hosts each of our components in an <a2ui-react-…> element: never a basic catalog element
    const custom = [...container.querySelectorAll("*")].map((e) => e.localName).filter((n) => n.includes("-"));
    expect(custom.filter((n) => !n.startsWith("a2ui-react-"))).toEqual([]);
  });

  it("reports the data model and whether every check passes", async () => {
    const onChange = vi.fn();
    render(<FormSurface message={message} onChange={onChange} />);
    const input = await screen.findByLabelText("Name");
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ name: "" }, false));
    await userEvent.type(input, "x");
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ name: "x" }, true));
  });

  it("shows the check message once the field was changed back to empty", async () => {
    render(<FormSurface message={message} />);
    const input = await screen.findByLabelText("Name");
    expect(screen.queryByText("A name is needed")).not.toBeInTheDocument();
    await userEvent.type(input, "x");
    await userEvent.clear(input);
    expect(await screen.findByText("A name is needed")).toBeInTheDocument();
  });
});
