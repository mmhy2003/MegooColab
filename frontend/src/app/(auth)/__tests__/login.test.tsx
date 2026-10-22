import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
const replace = vi.fn();
let search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => search,
}));

import { LoginForm, safeNext } from "@/app/(auth)/login/LoginForm";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function routeFetch(loginResponses: Response[]) {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/api/setup/status")) return json(200, { needs_setup: false });
    if (url.endsWith("/api/auth/login")) return loginResponses.shift()!;
    throw new Error(`unexpected ${url}`);
  });
}

async function submit(email = "a@x.io", password = "correct-horse-1") {
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value: email } });
  fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
}

describe("LoginForm", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    search = new URLSearchParams();
    Object.defineProperty(window, "location", {
      value: { ...window.location, pathname: "/login", search: "", assign: vi.fn() },
      writable: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    push.mockReset();
    replace.mockReset();
  });

  it("shows the code field after totp_required and sends the code", async () => {
    routeFetch([json(401, { detail: "totp_required" }), json(200, { user: { id: "1" } })]);
    render(<LoginForm />);
    await submit();
    const code = await screen.findByLabelText(/authenticator code/i);
    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/projects"));
    const loginCalls = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/api/auth/login"));
    const body = JSON.parse(String(loginCalls.at(-1)![1]!.body));
    expect(body.totp_code).toBe("123456");
  });

  it("explains wrong credentials", async () => {
    routeFetch([json(401, { detail: "invalid_credentials" })]);
    render(<LoginForm />);
    await submit();
    expect(await screen.findByText("Wrong email or password.")).toBeInTheDocument();
  });

  it("explains a locked account", async () => {
    routeFetch([json(423, { detail: "locked" })]);
    render(<LoginForm />);
    await submit();
    expect(await screen.findByText("Too many attempts. Try again in 15 minutes.")).toBeInTheDocument();
  });

  it("goes to next after signing in", async () => {
    search = new URLSearchParams({ next: "/projects/PAY/board" });
    routeFetch([json(200, { user: { id: "1" } })]);
    render(<LoginForm />);
    await submit();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/projects/PAY/board"));
  });

  it("ignores an off-site next", async () => {
    search = new URLSearchParams({ next: "https://evil.example/x" });
    routeFetch([json(200, { user: { id: "1" } })]);
    render(<LoginForm />);
    await submit();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/projects"));
  });

  it("sends first-run installs to setup", async () => {
    vi.mocked(fetch).mockResolvedValue(json(200, { needs_setup: true }));
    render(<LoginForm />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/setup"));
  });
});

describe("safeNext", () => {
  it.each(["https://evil.example", "//evil.example", "/\\evil.example", "/\\/evil.example", "javascript:alert(1)"])(
    "rejects %s",
    (next) => expect(safeNext(next)).toBe("/projects"),
  );
  it("keeps same-site paths", () => expect(safeNext("/projects/PAY/board?task=PAY-1")).toBe("/projects/PAY/board?task=PAY-1"));
});
