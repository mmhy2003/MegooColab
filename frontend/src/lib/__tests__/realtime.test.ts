import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { connectRealtime, invalidationsFor } from "@/lib/realtime";
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

  it("maps task events to the project's task lists and task details", () => {
    const out = invalidationsFor({ type: "task.updated", project_id: "p1", task_id: "t1" }, keys);
    expect(out).toContainEqual(["tasks", "PAY"]);
    expect(out).toContainEqual(["task"]);
    expect(out).toContainEqual(["activity"]);
    expect(out).toContainEqual(["columns", "PAY"]);
  });

  it("falls back to prefixes when the project key is unknown", () => {
    const out = invalidationsFor({ type: "task.created", project_id: "zzz" }, keys);
    expect(out).toContainEqual(["tasks"]);
  });

  it("maps comments to the activity thread only", () => {
    expect(invalidationsFor({ type: "comment.created", project_id: "p1" }, keys)).toEqual([["activity"]]);
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
