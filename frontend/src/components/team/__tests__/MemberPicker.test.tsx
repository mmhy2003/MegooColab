import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MemberPicker } from "@/components/team/MemberPicker";
import type { User } from "@/lib/types";

const user = (id: string, name: string, email: string): User => ({
  id,
  name,
  email,
  role: "member",
  status: "active",
  must_change_password: false,
  totp_enabled: false,
});

const USERS = [user("1", "Alice Smith", "alice@x.io"), user("2", "Bob Jones", "bob@x.io"), user("3", "Cara Diaz", "cara@x.io")];

const person = (name: string) => screen.queryByRole("option", { name: new RegExp(name) });

describe("MemberPicker", () => {
  it("filters by search text", async () => {
    render(<MemberPicker users={USERS} selected={[]} onSave={vi.fn()} />);
    await userEvent.type(screen.getByRole("combobox", { name: /search people/i }), "bob");
    expect(person("Alice Smith")).not.toBeInTheDocument();
    expect(person("Bob Jones")).toBeInTheDocument();
  });

  it("toggles membership and saves the selected ids", async () => {
    const onSave = vi.fn();
    render(<MemberPicker users={USERS} selected={["1"]} onSave={onSave} />);
    expect(person("Alice Smith")).toHaveAttribute("aria-checked", "true");
    await userEvent.click(person("Alice Smith")!);
    await userEvent.click(person("Cara Diaz")!);
    expect(person("Alice Smith")).toHaveAttribute("aria-checked", "false");
    expect(person("Cara Diaz")).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("button", { name: /save members/i }));
    expect(onSave).toHaveBeenCalledWith(["3"]);
  });

  it("is worked from the keyboard: arrows move, Enter ticks", async () => {
    render(<MemberPicker users={USERS} selected={[]} onSave={vi.fn()} />);
    await userEvent.click(screen.getByRole("combobox", { name: /search people/i }));
    await userEvent.keyboard("{ArrowDown}");
    expect(person("Bob Jones")).toHaveAttribute("aria-selected", "true"); // highlighted (Alice was first)
    await userEvent.keyboard("{Enter}");
    expect(person("Bob Jones")).toHaveAttribute("aria-checked", "true");
    expect(person("Alice Smith")).toHaveAttribute("aria-checked", "false");
  });

  it("hides deactivated people unless already selected", () => {
    const gone = { ...user("4", "Dan Old", "dan@x.io"), status: "deactivated" as const };
    render(<MemberPicker users={[...USERS, gone]} selected={[]} onSave={vi.fn()} />);
    expect(person("Dan Old")).not.toBeInTheDocument();
  });
});
