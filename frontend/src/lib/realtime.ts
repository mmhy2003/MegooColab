"use client";

import { useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";
import { useEffect } from "react";

import { qk } from "@/lib/queries";

export type LiveEvent = {
  type: string;
  project_id?: string | null;
  task_id?: string | null;
  user_id?: string | null;
  team_id?: string | null;
  space_id?: string | null;
};

const CLOSE_UNAUTHORIZED = 4401;
const MIN_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;

/** Which cached queries an event makes stale. "all" means refetch everything. */
export function invalidationsFor(event: LiveEvent, keyById: Map<string, string>): QueryKey[] | "all" {
  const key = event.project_id ? keyById.get(event.project_id) : undefined;
  const scoped = (name: string): QueryKey => (key ? [name, key] : [name]);
  const kind = event.type.split(".")[0];
  switch (kind) {
    case "task":
      return [scoped("tasks"), ["task"], ["workflow"], ["activity"], ["attachments"], scoped("columns"), ["burndown"], ["agent-runs"], ["documents"], ["document"], ["mockups"], ["records"], ["kb", "refs"], ["questions", "task"]];
    case "comment":
      return [["activity"]];
    case "columns":
      return [scoped("columns"), scoped("tasks")];
    case "project":
      return [qk.projects(), ["project"], scoped("labels"), scoped("repositories"), ["teams"], ["team"]];
    case "sprint":
      return [scoped("sprints"), ["burndown"], scoped("velocity"), scoped("tasks")];
    case "agents":
      // a project-scoped event whose project is not in the cached list still refreshes every project's agents
      return event.project_id ? [scoped("project-agents"), ["agents"], ["team"]] : [["agents"], ["team"]];
    case "question":
      return [["questions"], ["task"]];
    case "kb":
      return [["kb"]];
    case "notification":
      return [["notifications"]];
    case "membership":
      return "all";
    default:
      return [];
  }
}

/** The dashboard's queries: refetched at most once every THROTTLE_MS, whatever the event rate (an agent at work sends
 * many). The first event starts the window; the refetch runs at its end and takes in every event inside it. */
export const THROTTLE_MS = 2_000;

export function throttledFor(event: LiveEvent): QueryKey[] {
  switch (event.type.split(".")[0]) {
    case "task":
    case "question":
    case "notification":
      return [["dashboard"], ["dashboard-count"]];
    case "agents":
    case "sprint":
    case "project":
      return [["dashboard"]];
    default:
      return [];
  }
}

export function createThrottle(client: QueryClient, ms = THROTTLE_MS): { add(key: QueryKey): void; stop(): void } {
  const pending = new Map<string, QueryKey>();
  let timer: ReturnType<typeof setTimeout> | undefined;
  return {
    add(key) {
      pending.set(JSON.stringify(key), key);
      timer ??= setTimeout(() => {
        timer = undefined;
        const keys = [...pending.values()];
        pending.clear();
        for (const queryKey of keys) void client.invalidateQueries({ queryKey });
      }, ms);
    },
    stop() {
      clearTimeout(timer);
      timer = undefined;
      pending.clear();
    },
  };
}

function projectKeys(client: QueryClient): Map<string, string> {
  const projects = client.getQueryData<{ id: string; key: string }[]>(qk.projects()) ?? [];
  return new Map(projects.map((p) => [p.id, p.key]));
}

/** Opens the live-update socket; returns a function that closes it for good. */
export function connectRealtime(client: QueryClient): () => void {
  let socket: WebSocket | null = null;
  let stopped = false;
  let backoff = MIN_BACKOFF_MS;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let connectedBefore = false;
  const throttle = createThrottle(client);

  const open = () => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${scheme}://${window.location.host}/api/ws`);
    socket.onopen = () => {
      backoff = MIN_BACKOFF_MS;
      // events published while we were disconnected are gone: refetch rather than show stale data
      if (connectedBefore) void client.invalidateQueries();
      connectedBefore = true;
    };
    socket.onmessage = (msg) => {
      let event: LiveEvent;
      try {
        event = JSON.parse(String(msg.data));
      } catch {
        return;
      }
      if (event.type === "ping") return;
      const keys = invalidationsFor(event, projectKeys(client));
      if (keys === "all") void client.invalidateQueries();
      else for (const queryKey of keys) void client.invalidateQueries({ queryKey });
      for (const key of throttledFor(event)) throttle.add(key);
    };
    socket.onclose = (e) => {
      if (stopped) return;
      if (e.code === CLOSE_UNAUTHORIZED) {
        stopped = true;
        window.location.assign("/login");
        return;
      }
      timer = setTimeout(open, backoff);
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
    };
  };

  open();
  return () => {
    stopped = true;
    clearTimeout(timer);
    throttle.stop();
    socket?.close();
  };
}

export function useRealtime(): void {
  const client = useQueryClient();
  useEffect(() => connectRealtime(client), [client]);
}
