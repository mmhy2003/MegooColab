import { createHmac } from "node:crypto";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

/**
 * A GitHub Enterprise stand-in on the host: the REST API under /api/v3 that MegooColab lists repositories, reads
 * pull requests and manages webhooks with (backend/app/git/providers.py), for one repository `o/r`, with state the
 * test changes. The stack reaches it as http://host.docker.internal:<port> (deploy/docker-compose.yml extra_hosts).
 */

export type FakePr = {
  state: "open" | "closed";
  merged: boolean;
  /** the combined commit status: pending, success or failure */
  checks: "pending" | "success" | "failure";
  reviews: { state: string; login: string }[];
};

export type FakeGit = {
  port: number;
  /** what the backend uses: http://host.docker.internal:<port> */
  baseUrl: string;
  token: string;
  prs: Map<number, FakePr>;
  /** `o/r`'s webhooks by id, as MegooColab created or updated them */
  hooks: Map<string, { url: string; secret: string }>;
  /** every API path asked for, in order */
  requests: string[];
  close(): Promise<void>;
};

const SHA = (n: number) => `${String(n).repeat(40)}`.slice(0, 40);

export async function startFakeGit(token: string): Promise<FakeGit> {
  const prs = new Map<number, FakePr>();
  const requests: string[] = [];
  const hooks = new Map<string, { url: string; secret: string }>();
  let nextHook = 1;
  const server: Server = createServer(async (req, res) => {
    const path = (req.url ?? "").split("?")[0];
    requests.push(path);
    const send = (status: number, body: unknown) => {
      res.writeHead(status, { "content-type": "application/json" });
      res.end(body === null ? undefined : JSON.stringify(body));
    };
    let raw = "";
    for await (const chunk of req) raw += chunk;
    const config = () => (JSON.parse(raw || "{}") as { config: { url: string; secret: string } }).config;
    const hookOut = (id: string) => ({ id: Number(id), config: { url: hooks.get(id)!.url } });
    if (req.headers.authorization !== `Bearer ${token}`) return send(401, { message: "Bad credentials" });
    if (path === "/api/v3/user") return send(200, { login: "fake-bot" });
    if (path === "/api/v3/user/repos") {
      const page = Number(new URL(req.url ?? "", "http://x").searchParams.get("page") ?? "1");
      return send(200, page === 1 ? [{ full_name: "o/r", html_url: `${baseUrl}/o/r`, default_branch: "main" }] : []);
    }
    if (path === "/api/v3/repos/o/r/hooks") {
      if (req.method === "POST") {
        const id = String(nextHook++);
        hooks.set(id, { url: config().url, secret: config().secret });
        return send(201, hookOut(id));
      }
      return send(200, [...hooks.keys()].map(hookOut));
    }
    let m = /^\/api\/v3\/repos\/o\/r\/hooks\/(\d+)$/.exec(path);
    if (m) {
      const id = m[1];
      if (!hooks.has(id)) return send(404, { message: "Not Found" });
      if (req.method === "DELETE") {
        hooks.delete(id);
        return send(204, null);
      }
      hooks.set(id, { url: config().url, secret: config().secret });
      return send(200, hookOut(id));
    }
    m = /^\/api\/v3\/repos\/o\/r\/pulls\/(\d+)(\/reviews)?$/.exec(path);
    if (m) {
      const n = Number(m[1]);
      const pr = prs.get(n);
      if (!pr) return send(404, { message: "Not Found" });
      if (m[2]) return send(200, pr.reviews.map((r) => ({ state: r.state, user: { login: r.login } })));
      return send(200, {
        number: n,
        state: pr.state,
        merged: pr.merged,
        merged_at: pr.merged ? new Date().toISOString() : null,
        head: { sha: SHA(n) },
      });
    }
    m = /^\/api\/v3\/repos\/o\/r\/commits\/([0-9a-f]{40})\/(status|check-runs)$/.exec(path);
    if (m) {
      const pr = [...prs.entries()].find(([n]) => SHA(n) === m![1])?.[1];
      if (!pr) return send(404, { message: "Not Found" });
      if (m[2] === "check-runs") return send(200, { total_count: 0, check_runs: [] });
      return send(200, { state: pr.checks, total_count: 1, statuses: [{ state: pr.checks, context: "ci" }] });
    }
    send(404, { message: "Not Found" });
  });
  await new Promise<void>((done) => server.listen(0, "0.0.0.0", done));
  const port = (server.address() as AddressInfo).port;
  const baseUrl = `http://host.docker.internal:${port}`;
  return {
    port,
    baseUrl,
    token,
    prs,
    hooks,
    requests,
    close: () => new Promise<void>((done) => server.close(() => done())),
  };
}

let deliveries = 0;

/** A GitHub webhook delivery of `event` about `o/r`, signed (X-Hub-Signature-256) with `secret`, with its own id. */
export function delivery(event: string, payload: object, secret: string): { body: string; headers: Record<string, string> } {
  const body = JSON.stringify({ repository: { full_name: "o/r" }, ...payload });
  const signature = `sha256=${createHmac("sha256", secret).update(body).digest("hex")}`;
  deliveries += 1;
  return {
    body,
    headers: {
      "content-type": "application/json",
      "X-GitHub-Event": event,
      "X-GitHub-Delivery": `e2e-${Date.now()}-${deliveries}`,
      "X-Hub-Signature-256": signature,
    },
  };
}

/** `o/r` #n merged by `mo` from task branch `megoo/GIT-<n>`: a GitHub `pull_request` delivery signed with `secret`. */
export function pullRequestDelivery(n: number, secret: string, htmlUrl = `https://git.example/o/r/pull/${n}`) {
  const pullRequest = { number: n, html_url: htmlUrl, merged: true, head: { ref: `megoo/GIT-${n}` }, base: { ref: "main" } };
  return delivery("pull_request", { action: "closed", number: n, pull_request: pullRequest, sender: { login: "mo" } }, secret);
}
