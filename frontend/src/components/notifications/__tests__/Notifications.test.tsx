import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationBell } from "@/components/notifications/NotificationBell";
import { NotificationList } from "@/components/notifications/NotificationList";
import { NotificationPrefs } from "@/components/notifications/NotificationPrefs";
import type { Notification } from "@/lib/notifications";

type Handler = (url: string, init?: RequestInit) => Response | undefined;

function mockFetch(handler: Handler) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => handler(url, init) ?? new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

function note(i: number, read = false): Notification {
  return {
    id: `n${i}`, kind: "assigned", title: `Ahmed assigned you PAY-${i}`, body: "Fix login", link: `/projects/PAY/board?task=PAY-${i}`,
    task_id: null, project_id: null, created_at: `2026-10-27T10:${String(i).padStart(2, "0")}:00Z`, read_at: read ? "2026-10-27T11:00:00Z" : null,
  };
}

const posts = (fetchMock: ReturnType<typeof mockFetch>) =>
  fetchMock.mock.calls.filter(([, i]) => i?.method === "POST").map(([u]) => u);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("NotificationBell", () => {
  it("shows unread count and marks read", async () => {
    let count = 2;
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/notifications/unread-count") return json({ count });
      if (url.startsWith("/api/notifications?") && !init?.method) return json([note(2), note(1, true)]);
      if (url === "/api/notifications/n2/read") count = 1;
      if (url === "/api/notifications/read-all") count = 0;
      return undefined;
    });
    wrap(<NotificationBell />);
    const bell = screen.getByRole("button", { name: "Notifications" });
    expect(await within(bell).findByText("2")).toBeInTheDocument();
    fireEvent.click(bell);
    const link = await screen.findByRole("link", { name: /Ahmed assigned you PAY-2/ });
    expect(link).toHaveAttribute("href", "/projects/PAY/board?task=PAY-2");
    fireEvent.click(link);
    await waitFor(() => expect(posts(fetchMock)).toContain("/api/notifications/n2/read"));
    fireEvent.click(bell);
    fireEvent.click(await screen.findByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(posts(fetchMock)).toContain("/api/notifications/read-all"));
    await waitFor(() => expect(within(bell).queryByText(/\d/)).toBeNull()); // no badge at 0
  });
});

describe("NotificationList", () => {
  it("pages and links", async () => {
    const first = Array.from({ length: 50 }, (_, i) => note(59 - i));
    const fetchMock = mockFetch((url) => {
      if (url === "/api/notifications?unread=false") return json(first);
      if (url.startsWith("/api/notifications?unread=false&before=")) return json([note(9)]);
      if (url.startsWith("/api/notifications?unread=true")) return json([note(59)]);
      return undefined;
    });
    wrap(<NotificationList />);
    expect(await screen.findAllByRole("listitem")).toHaveLength(50);
    expect(screen.getByRole("link", { name: /PAY-59/ })).toHaveAttribute("href", "/projects/PAY/board?task=PAY-59");
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("link", { name: /PAY-9$/ })).toBeInTheDocument();
    const next = fetchMock.mock.calls.map(([u]) => u).find((u) => u.includes("before="))!;
    const params = new URL(next, "http://x").searchParams;
    expect(params.get("before")).toBe(first[49].created_at);
    expect(params.get("before_id")).toBe(first[49].id);
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull(); // a short page is the last
    fireEvent.click(screen.getByRole("checkbox", { name: "Unread only" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
  });

  it("says when there is nothing", async () => {
    mockFetch(() => json([]));
    wrap(<NotificationList />);
    expect(await screen.findByText("No notifications yet.")).toBeInTheDocument();
  });
});

describe("NotificationPrefs", () => {
  it("toggles in-app and email per kind", async () => {
    const prefs = [
      { kind: "needs_you", in_app: true, email: true },
      { kind: "assigned", in_app: true, email: true },
      { kind: "mentioned", in_app: true, email: true },
      { kind: "agent_offline", in_app: true, email: true },
      { kind: "question_waiting", in_app: true, email: false },
    ];
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/me/notification-preferences" && !init?.method) return json(prefs);
      if (url === "/api/me/notification-preferences" && init?.method === "PUT") {
        const [p] = JSON.parse(String(init.body));
        return json(prefs.map((x) => (x.kind === p.kind ? p : x)));
      }
      return undefined;
    });
    wrap(<NotificationPrefs />);
    const email = await screen.findByRole("checkbox", { name: "Email: Assigned to me" });
    expect(email).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Email: A question waits for an answer" })).not.toBeChecked();
    fireEvent.click(email);
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PUT")).toBe(true));
    const put = fetchMock.mock.calls.find(([, i]) => i?.method === "PUT")!;
    expect(JSON.parse(String(put[1]!.body))).toEqual([{ kind: "assigned", in_app: true, email: false }]);
    fireEvent.click(screen.getByRole("checkbox", { name: "In app: Mentioned in a comment" }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, i]) => i?.method === "PUT")).toHaveLength(2));
  });

  it("has a Push column, unticked by default, saved per kind", async () => {
    const prefs = [
      { kind: "assigned", in_app: true, email: true, push: false },
      { kind: "mentioned", in_app: true, email: false, push: false },
    ];
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/me/notification-preferences" && !init?.method) return json(prefs);
      if (url === "/api/me/notification-preferences" && init?.method === "PUT") return json(JSON.parse(String(init.body)));
      return undefined;
    });
    wrap(<NotificationPrefs />);
    const push = await screen.findByRole("checkbox", { name: "Push: Mentioned in a comment" });
    expect(screen.getByRole("columnheader", { name: "Push" })).toBeTruthy();
    expect(push).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Push: Assigned to me" })).not.toBeChecked();
    fireEvent.click(push);
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PUT")).toBe(true));
    const put = fetchMock.mock.calls.find(([, i]) => i?.method === "PUT")!;
    expect(JSON.parse(String(put[1]!.body))).toEqual([{ kind: "mentioned", in_app: true, email: false, push: true }]);
  });

  it("shows a toggle at once, and puts it back when saving fails", async () => {
    const prefs = [{ kind: "assigned", in_app: true, email: true }];
    let fail: (r: Response) => void = () => undefined;
    // the save stays pending until the test answers it
    const fetchMock = vi.fn((_url: string, init?: RequestInit) =>
      init?.method === "PUT" ? new Promise<Response>((done) => (fail = done)) : Promise.resolve(json(prefs)));
    vi.stubGlobal("fetch", fetchMock);
    wrap(<NotificationPrefs />);
    const inApp = await screen.findByRole("checkbox", { name: "In app: Assigned to me" });
    fireEvent.click(inApp);
    expect(inApp).not.toBeChecked(); // at once, before the server answers
    await waitFor(() => expect(fetchMock.mock.calls.some(([, i]) => i?.method === "PUT")).toBe(true));
    fail(new Response(JSON.stringify({ detail: "validation_error" }), { status: 422 }));
    await waitFor(() => expect(inApp).toBeChecked());
    expect(screen.getByRole("alert")).toHaveTextContent("Some fields are invalid.");
  });
});
