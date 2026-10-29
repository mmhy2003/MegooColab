import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { connectRealtime, invalidationsFor, THROTTLE_MS, throttledFor } from "@/lib/realtime";
import { qk } from "@/lib/queries";

class MockSocket {
  static instances: MockSocket[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onopen: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    MockSocket.instances.push(this);
  }
  close() {
    this.closed = true;
  }
  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

describe("invalidationsFor", () => {
  const keys = new Map([["p1", "PAY"]]);

  it("refreshes the bell and the list on a notification event", () => {
    expect(invalidationsFor({ type: "notification.created", user_id: "u1" }, keys)).toEqual([["notifications"]]);
  });

  it("maps task events to the project's task lists and task details", () => {
    const out = invalidationsFor({ type: "task.updated", project_id: "p1", task_id: "t1" }, keys);
    expect(out).toContainEqual(["tasks", "PAY"]);
    expect(out).toContainEqual(["task"]);
    expect(out).toContainEqual(["records"]);
    expect(out).toContainEqual(["workflow"]);
    expect(out).toContainEqual(["activity"]);
    expect(out).toContainEqual(["agent-runs"]);
    expect(out).toContainEqual(["columns", "PAY"]);
    expect(out).toContainEqual(["documents"]);
    expect(out).toContainEqual(["document"]);
    expect(out).toContainEqual(["mockups"]);
  });

  it("falls back to prefixes when the project key is unknown", () => {
    const out = invalidationsFor({ type: "task.created", project_id: "zzz" }, keys);
    expect(out).toContainEqual(["tasks"]);
  });

  it("maps comments to the activity thread only", () => {
    expect(invalidationsFor({ type: "comment.created", project_id: "p1" }, keys)).toEqual([["activity"]]);
  });

  it("maps project-scoped agent events to project agents and my agents", () => {
    expect(invalidationsFor({ type: "agents.updated", project_id: "p1" }, keys)).toEqual([["project-agents", "PAY"], ["agents"], ["team"]]);
  });

  it("still refreshes every project's agents when the project list is not cached", () => {
    expect(invalidationsFor({ type: "agents.updated", project_id: "unknown" }, keys)).toEqual([["project-agents"], ["agents"], ["team"]]);
  });

  it("maps user-only agent events to my agents", () => {
    expect(invalidationsFor({ type: "agents.updated", user_id: "u" }, keys)).toEqual([["agents"], ["team"]]);
  });

  it("invalidates everything on membership changes", () => {
    expect(invalidationsFor({ type: "membership.changed", user_id: "u" }, keys)).toEqual("all");
  });
});

describe("connectRealtime", () => {
  let client: QueryClient;
  const assign = vi.fn();

  beforeEach(() => {
    MockSocket.instances = [];
    vi.stubGlobal("WebSocket", MockSocket);
    vi.useFakeTimers();
    client = new QueryClient();
    client.setQueryData(qk.projects(), [{ id: "p1", key: "PAY" }]);
    Object.defineProperty(window, "location", {
      value: { ...window.location, protocol: "http:", host: "localhost:8080", assign },
      writable: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    assign.mockReset();
  });

  it("connects to /api/ws and invalidates on task.updated", () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    const stop = connectRealtime(client);
    const ws = MockSocket.instances[0];
    expect(ws.url).toBe("ws://localhost:8080/api/ws");
    ws.emit({ type: "task.updated", project_id: "p1", task_id: "t1" });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["tasks", "PAY"] });
    stop();
    expect(ws.closed).toBe(true);
  });

  it("ignores pings", () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    connectRealtime(client);
    MockSocket.instances[0].emit({ type: "ping" });
    expect(spy).not.toHaveBeenCalled();
  });

  it("sends the user to login when the server closes with 4401", () => {
    connectRealtime(client);
    MockSocket.instances[0].onclose?.({ code: 4401 });
    expect(assign).toHaveBeenCalledWith("/login");
    vi.advanceTimersByTime(60_000);
    expect(MockSocket.instances).toHaveLength(1);
  });

  it("refetches everything after reconnecting, since events may have been missed", () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    connectRealtime(client);
    MockSocket.instances[0].onopen?.();
    expect(spy).not.toHaveBeenCalled();
    MockSocket.instances[0].onclose?.({ code: 1006 });
    vi.advanceTimersByTime(1000);
    MockSocket.instances[1].onopen?.();
    expect(spy).toHaveBeenCalledWith();
  });

  it("reconnects with backoff after other closes", () => {
    connectRealtime(client);
    MockSocket.instances[0].onclose?.({ code: 1006 });
    vi.advanceTimersByTime(999);
    expect(MockSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(MockSocket.instances).toHaveLength(2);
    MockSocket.instances[1].onclose?.({ code: 1006 });
    vi.advanceTimersByTime(1999);
    expect(MockSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(MockSocket.instances).toHaveLength(3);
  });
});

describe("dashboard throttle", () => {
  let client: QueryClient;

  beforeEach(() => {
    MockSocket.instances = [];
    vi.stubGlobal("WebSocket", MockSocket);
    vi.useFakeTimers();
    client = new QueryClient();
    Object.defineProperty(window, "location", {
      value: { ...window.location, protocol: "http:", host: "localhost:8080", assign: vi.fn() },
      writable: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  const calls = (spy: { mock: { calls: unknown[][] } }, key: string) =>
    spy.mock.calls.filter(([f]) => JSON.stringify((f as { queryKey?: unknown } | undefined)?.queryKey) === key).length;

  it("maps events to the dashboard and the badge", () => {
    expect(throttledFor({ type: "task.updated" })).toEqual([["dashboard"], ["dashboard-count"]]);
    expect(throttledFor({ type: "notification.created" })).toEqual([["dashboard"], ["dashboard-count"]]);
    expect(throttledFor({ type: "question.updated" })).toEqual([["dashboard"], ["dashboard-count"]]);
    expect(throttledFor({ type: "agents.changed" })).toEqual([["dashboard"]]);
    expect(throttledFor({ type: "sprint.updated" })).toEqual([["dashboard"]]);
    expect(throttledFor({ type: "project.updated" })).toEqual([["dashboard"]]);
    expect(throttledFor({ type: "columns.updated" })).toEqual([["dashboard"]]);
    expect(throttledFor({ type: "kb.changed" })).toEqual([]);
  });

  it("refetches once at the end of the window however many events arrive", () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    connectRealtime(client);
    const socket = MockSocket.instances[0];
    for (let i = 0; i < 50; i++) socket.emit({ type: "task.updated", project_id: "p1" });
    expect(calls(spy, '["dashboard"]')).toBe(0);
    vi.advanceTimersByTime(THROTTLE_MS);
    expect(calls(spy, '["dashboard"]')).toBe(1);
    expect(calls(spy, '["dashboard-count"]')).toBe(1);
    socket.emit({ type: "agents.changed" });
    vi.advanceTimersByTime(THROTTLE_MS);
    expect(calls(spy, '["dashboard"]')).toBe(2);
    expect(calls(spy, '["dashboard-count"]')).toBe(1);
  });

  it("stops the pending refetch when closed", () => {
    const spy = vi.spyOn(client, "invalidateQueries");
    const close = connectRealtime(client);
    MockSocket.instances[0].emit({ type: "task.updated" });
    close();
    vi.advanceTimersByTime(THROTTLE_MS * 2);
    expect(calls(spy, '["dashboard"]')).toBe(0);
  });
});
