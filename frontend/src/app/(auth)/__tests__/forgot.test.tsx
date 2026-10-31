import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

let search = new URLSearchParams();
vi.mock("next/navigation", () => ({ useSearchParams: () => search }));

import ForgotPage from "@/app/(auth)/forgot/page";

afterEach(() => {
  cleanup();
  search = new URLSearchParams();
});

describe("Forgot password", () => {
  it("starts with the email of the account it was opened for", async () => {
    search = new URLSearchParams({ email: "mo@acme.io" });
    render(<ForgotPage />);
    expect(await screen.findByLabelText("Email")).toHaveValue("mo@acme.io");
  });

  it("starts empty otherwise", async () => {
    render(<ForgotPage />);
    expect(await screen.findByLabelText("Email")).toHaveValue("");
  });
});
