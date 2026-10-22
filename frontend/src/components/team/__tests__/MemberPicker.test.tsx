import { fireEvent, render, screen } from "@testing-library/react";
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

describe("MemberPicker", () => {
  it("filters by search text", () => {
    render(<MemberPicker users={USERS} selected={[]} onSave={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/search people/i), { target: { value: "bob" } });
    expect(screen.queryByLabelText("Alice Smith")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Bob Jones")).toBeInTheDocument();
  });

  it("toggles membership and saves the selected ids", () => {
    const onSave = vi.fn();
    render(<MemberPicker users={USERS} selected={["1"]} onSave={onSave} />);
    fireEvent.click(screen.getByLabelText("Alice Smith"));
    fireEvent.click(screen.getByLabelText("Cara Diaz"));
    fireEvent.click(screen.getByRole("button", { name: /save members/i }));
    expect(onSave).toHaveBeenCalledWith(["3"]);
  });

  it("hides deactivated people unless already selected", () => {
    const gone = { ...user("4", "Dan Old", "dan@x.io"), status: "deactivated" as const };
    render(<MemberPicker users={[...USERS, gone]} selected={[]} onSave={vi.fn()} />);
    expect(screen.queryByLabelText("Dan Old")).not.toBeInTheDocument();
  });
});
