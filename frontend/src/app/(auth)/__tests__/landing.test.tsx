import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ChangePasswordPage from "@/app/(auth)/change-password/page";
import InvitePage from "@/app/(auth)/invite/[token]/page";
import SetupPage from "@/app/(auth)/setup/page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useParams: () => ({ token: "t1" }),
}));

async function choosePassword() {
  await userEvent.type(screen.getByLabelText("New password"), "a-long-password-1");
  await userEvent.type(screen.getByLabelText("Confirm new password"), "a-long-password-1");
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ needs_setup: true }), { status: 200 })));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  push.mockReset();
});

describe("after setting a password, people land on the dashboard", () => {
  it("first-run setup", async () => {
    render(<SetupPage />);
    await userEvent.type(screen.getByLabelText("Organization name"), "Acme");
    await userEvent.type(screen.getByLabelText("Your name"), "Ada");
    await userEvent.type(screen.getByLabelText("Email"), "ada@acme.io");
    await choosePassword();
    await userEvent.click(screen.getByRole("button", { name: "Create organization" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
  });

  it("accepting an invite", async () => {
    render(<InvitePage />);
    await choosePassword();
    await userEvent.click(screen.getByRole("button", { name: "Join" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
  });

  it("the forced password change", async () => {
    render(<ChangePasswordPage />);
    await userEvent.type(screen.getByLabelText("Current password"), "old-password-1");
    await choosePassword();
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
  });
});
