import { afterEach, describe, expect, it, vi } from "vitest";

import { forgetAccount, readAccounts, rememberAccount, renameAccount } from "@/lib/accounts";

afterEach(() => {
  localStorage.clear();
  vi.useRealTimers();
});

describe("remembered accounts", () => {
  it("keeps the email and name only, the latest first", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-31T10:00:00Z"));
    rememberAccount({ email: "mo@acme.io", name: "Mohamed" });
    vi.setSystemTime(new Date("2026-10-31T11:00:00Z"));
    rememberAccount({ email: "admin@acme.io", name: "Mohamed (admin)" });
    expect(readAccounts().map((a) => a.email)).toEqual(["admin@acme.io", "mo@acme.io"]);
    expect(Object.keys(readAccounts()[0]).sort()).toEqual(["email", "lastUsed", "name"]);
  });

  it("signing in again moves the account to the top, with its current name, without a duplicate", () => {
    rememberAccount({ email: "mo@acme.io", name: "Mo" });
    rememberAccount({ email: "admin@acme.io", name: "Admin" });
    rememberAccount({ email: "MO@acme.io ", name: "Mohamed" });
    expect(readAccounts().map((a) => [a.email, a.name])).toEqual([["mo@acme.io", "Mohamed"], ["admin@acme.io", "Admin"]]);
  });

  it("keeps at most 10, dropping the least recently used", () => {
    for (let i = 1; i <= 12; i++) rememberAccount({ email: `u${i}@x.io`, name: `U${i}` });
    const emails = readAccounts().map((a) => a.email);
    expect(emails).toHaveLength(10);
    expect(emails[0]).toBe("u12@x.io");
    expect(emails).not.toContain("u1@x.io");
  });

  it("forgets one account", () => {
    rememberAccount({ email: "mo@acme.io", name: "Mo" });
    rememberAccount({ email: "admin@acme.io", name: "Admin" });
    forgetAccount("mo@acme.io");
    expect(readAccounts().map((a) => a.email)).toEqual(["admin@acme.io"]);
  });

  it("renames a remembered account, and doesn't add one that isn't remembered", () => {
    rememberAccount({ email: "mo@acme.io", name: "Mo" });
    renameAccount({ email: "mo@acme.io", name: "Mohamed" });
    renameAccount({ email: "new@acme.io", name: "New" });
    expect(readAccounts().map((a) => [a.email, a.name])).toEqual([["mo@acme.io", "Mohamed"]]);
  });

  it("reads nothing from broken or blocked storage", () => {
    localStorage.setItem("megoo-accounts", "{not json");
    expect(readAccounts()).toEqual([]);
    localStorage.setItem("megoo-accounts", JSON.stringify([{ email: 1 }, { email: "ok@x.io", name: "Ok", lastUsed: 1 }]));
    expect(readAccounts().map((a) => a.email)).toEqual(["ok@x.io"]);
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readAccounts()).toEqual([]);
    expect(() => rememberAccount({ email: "a@x.io", name: "A" })).not.toThrow();
    get.mockRestore();
  });
});

describe("useKeepAccountName", () => {
  it("brings a remembered account's name up to date when the app loads", async () => {
    const { render } = await import("@testing-library/react");
    const { useKeepAccountName } = await import("@/lib/accounts");
    rememberAccount({ email: "mo@acme.io", name: "Mo" });
    function App() {
      useKeepAccountName({ email: "mo@acme.io", name: "Mohamed" });
      return null;
    }
    render(<App />);
    expect(readAccounts()[0].name).toBe("Mohamed");
  });
});
