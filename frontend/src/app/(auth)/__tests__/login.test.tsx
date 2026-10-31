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
import { readAccounts, rememberAccount } from "@/lib/accounts";

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
    localStorage.clear();
  });

  it("shows the code field after totp_required and sends the code", async () => {
    routeFetch([json(401, { detail: "totp_required" }), json(200, { user: { id: "1" } })]);
    render(<LoginForm />);
    await submit();
    const code = await screen.findByLabelText(/authenticator code/i);
    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
    const loginCalls = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/api/auth/login"));
    const body = JSON.parse(String(loginCalls.at(-1)![1]!.body));
    expect(body.totp_code).toBe("123456");
  });

  it("starts with the cursor in the email field", () => {
    routeFetch([]);
    render(<LoginForm />);
    expect(screen.getByLabelText(/email/i)).toHaveFocus();
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
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
  });

  it("sends first-run installs to setup", async () => {
    vi.mocked(fetch).mockResolvedValue(json(200, { needs_setup: true }));
    render(<LoginForm />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/setup"));
  });
});

describe("LoginForm with remembered accounts", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    search = new URLSearchParams();
    rememberAccount({ email: "mo@acme.io", name: "Mohamed Youssef" });
    rememberAccount({ email: "admin@acme.io", name: "Mohamed (admin)" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    push.mockReset();
    localStorage.clear();
  });

  const loginBodies = () =>
    vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/api/auth/login")).map(([, init]) => JSON.parse(String(init!.body)));

  it("lists the accounts, the latest first, instead of the form", () => {
    routeFetch([]);
    render(<LoginForm />);
    expect(screen.getByRole("heading", { name: "Choose an account" })).toBeInTheDocument();
    const accounts = screen.getAllByRole("button", { name: /^Mohamed/ });
    expect(accounts.map((b) => b.textContent)).toEqual([
      expect.stringContaining("Mohamed (admin)admin@acme.io"),
      expect.stringContaining("Mohamed Youssefmo@acme.io"),
    ]);
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
  });

  it("asks only for the password of the account picked, and signs it in", async () => {
    routeFetch([json(200, { user: { id: "1", email: "mo@acme.io", name: "Mohamed Youssef" } })]);
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: /^Mohamed Youssef/ }));
    expect(screen.getByText("mo@acme.io")).toBeInTheDocument();
    const password = screen.getByLabelText(/^password/i);
    expect(password).toHaveFocus();
    // the email goes along unseen, so a password manager fills this account's password
    expect(screen.getByDisplayValue("mo@acme.io")).toHaveAttribute("autocomplete", "username");
    fireEvent.change(password, { target: { value: "correct-horse-1" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
    expect(loginBodies()[0]).toMatchObject({ email: "mo@acme.io", password: "correct-horse-1" });
    expect(readAccounts()[0].email).toBe("mo@acme.io"); // used last: first now
  });

  it("keeps the account on a wrong password, and Switch goes back to the list", async () => {
    routeFetch([json(401, { detail: "invalid_credentials" })]);
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: /^Mohamed Youssef/ }));
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "nope-nope-nope" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Wrong email or password.")).toBeInTheDocument();
    expect(screen.getByText("mo@acme.io")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Switch" }));
    expect(screen.getByRole("heading", { name: "Choose an account" })).toBeInTheDocument();
  });

  it("asks for the authenticator code after the password of a picked account", async () => {
    routeFetch([json(401, { detail: "totp_required" }), json(200, { user: { id: "1", email: "mo@acme.io", name: "Mo" } })]);
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: /^Mohamed Youssef/ }));
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: "correct-horse-1" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    fireEvent.change(await screen.findByLabelText(/authenticator code/i), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
    expect(loginBodies()[1]).toMatchObject({ email: "mo@acme.io", totp_code: "123456" });
  });

  it("offers the reset with the account's email", () => {
    routeFetch([]);
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: /^Mohamed Youssef/ }));
    expect(screen.getByRole("link", { name: "Forgot your password?" })).toHaveAttribute("href", "/forgot?email=mo%40acme.io");
  });

  it("uses another account with the form, and goes back to the list", async () => {
    routeFetch([json(200, { user: { id: "2", email: "new@x.io", name: "New Person" } })]);
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: "Use another account" }));
    fireEvent.click(screen.getByRole("button", { name: "← Back to my accounts" }));
    fireEvent.click(screen.getByRole("button", { name: "Use another account" }));
    await submit("new@x.io");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
    expect(readAccounts()[0]).toMatchObject({ email: "new@x.io", name: "New Person" });
  });

  it("forgets an account with ×, and shows the form when none are left", () => {
    routeFetch([]);
    render(<LoginForm />);
    fireEvent.click(screen.getByRole("button", { name: "Forget admin@acme.io on this browser" }));
    expect(screen.queryByRole("button", { name: /^Mohamed \(admin\)/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Forget mo@acme.io on this browser" }));
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(readAccounts()).toEqual([]);
  });
});

describe("safeNext", () => {
  it.each(["https://evil.example", "//evil.example", "/\\evil.example", "/\\/evil.example", "javascript:alert(1)"])(
    "rejects %s",
    (next) => expect(safeNext(next)).toBe("/"),
  );
  it("keeps same-site paths", () => expect(safeNext("/projects/PAY/board?task=PAY-1")).toBe("/projects/PAY/board?task=PAY-1"));
});
