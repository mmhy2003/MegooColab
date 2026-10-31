import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const createPasskey = vi.fn();
const getPasskey = vi.fn();
vi.mock("@/lib/passkeys", () => ({
  createPasskey: (o: unknown) => createPasskey(o),
  getPasskey: (o: unknown) => getPasskey(o),
  isDismissed: (err: unknown) => (err as { name?: string })?.name === "NotAllowedError",
  passkeyProblem: () => null,
  guessPasskeyName: () => "Windows",
}));

import { PasskeysSection, TwoFactorStatus } from "@/components/auth/PasskeysSection";

const LIST = [
  { id: "p1", name: "Work laptop", created_at: "2026-10-30T09:00:00Z", last_used_at: "2026-10-31T09:00:00Z" },
  { id: "p2", name: "iPhone", created_at: "2026-10-31T09:00:00Z", last_used_at: null },
];

let list = LIST;
const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
  if (url === "/api/auth/passkeys" && (!init?.method || init.method === "GET")) return new Response(JSON.stringify(list));
  if (url.endsWith("/options")) return new Response(JSON.stringify({ challenge: "reg" }));
  if (url.endsWith("/remove-options")) return new Response(JSON.stringify({ challenge: "rm" }));
  if (url === "/api/auth/passkeys" && init?.method === "POST") return new Response(JSON.stringify({ id: "p3" }), { status: 201 });
  return new Response(null, { status: 204 });
});

function show(ui: React.ReactNode) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
}

const calls = (method: string, url: string | RegExp) =>
  fetchMock.mock.calls.filter(([u, init]) => (init?.method ?? "GET") === method && (typeof url === "string" ? u === url : url.test(u)));

beforeEach(() => {
  list = LIST;
  vi.stubGlobal("fetch", fetchMock);
  createPasskey.mockReset();
  getPasskey.mockReset();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  fetchMock.mockClear();
});

describe("PasskeysSection", () => {
  it("lists the passkeys with when they were added and last used", async () => {
    show(<PasskeysSection totpEnabled={false} />);
    const row = (await screen.findByText("iPhone")).closest("li")!;
    expect(row).toHaveTextContent(/Added .* · last used never/);
    expect(screen.getByText("Work laptop").closest("li")).not.toHaveTextContent("never");
  });

  it("adds one: the browser creates it, then it gets a name", async () => {
    createPasskey.mockResolvedValue({ id: "cred" });
    show(<PasskeysSection totpEnabled={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Add a passkey" }));
    const name = await screen.findByLabelText("Passkey name");
    expect(name).toHaveValue("Windows");
    fireEvent.change(name, { target: { value: "Desk PC" } });
    fireEvent.click(screen.getByRole("button", { name: "Save passkey" }));
    await waitFor(() => expect(calls("POST", "/api/auth/passkeys")).toHaveLength(1));
    expect(JSON.parse(String(calls("POST", "/api/auth/passkeys")[0][1]!.body))).toEqual({ name: "Desk PC", credential: { id: "cred" } });
    expect(createPasskey).toHaveBeenCalledWith({ challenge: "reg" });
  });

  it("a dismissed prompt adds nothing and says so", async () => {
    createPasskey.mockRejectedValue(Object.assign(new Error("x"), { name: "NotAllowedError" }));
    show(<PasskeysSection totpEnabled={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Add a passkey" }));
    expect(await screen.findByText("The passkey wasn't added.")).toBeInTheDocument();
    expect(calls("POST", "/api/auth/passkeys")).toHaveLength(0);
  });

  it("removes one with the password and a passkey", async () => {
    getPasskey.mockResolvedValue({ id: "assert" });
    show(<PasskeysSection totpEnabled={false} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove iPhone" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Password"), { target: { value: "correct-horse-1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm with passkey" }));
    await waitFor(() => expect(calls("DELETE", "/api/auth/passkeys/p2")).toHaveLength(1));
    expect(JSON.parse(String(calls("DELETE", "/api/auth/passkeys/p2")[0][1]!.body))).toEqual({ password: "correct-horse-1", passkey: { id: "assert" } });
    expect(getPasskey).toHaveBeenCalledWith({ challenge: "rm" });
    expect(within(dialog).queryByLabelText("Authenticator code")).toBeNull(); // no app: no code
  });

  it("with an app, removes with the password and a code", async () => {
    show(<PasskeysSection totpEnabled />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove iPhone" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Password"), { target: { value: "correct-horse-1" } });
    fireEvent.change(within(dialog).getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove with code" }));
    await waitFor(() => expect(calls("DELETE", "/api/auth/passkeys/p2")).toHaveLength(1));
    expect(JSON.parse(String(calls("DELETE", "/api/auth/passkeys/p2")[0][1]!.body))).toEqual({ password: "correct-horse-1", totp_code: "123456" });
  });
});

describe("TwoFactorStatus", () => {
  it("is on with an app or any passkey, off with neither", async () => {
    show(<TwoFactorStatus totpEnabled={false} />);
    expect(await screen.findByText("Two-factor sign-in is on.")).toBeInTheDocument();
    cleanup();
    list = [];
    show(<TwoFactorStatus totpEnabled={false} />);
    expect(await screen.findByText("Two-factor sign-in is off.")).toBeInTheDocument();
    cleanup();
    show(<TwoFactorStatus totpEnabled />);
    expect(await screen.findByText("Two-factor sign-in is on.")).toBeInTheDocument();
  });
});
