import { createHmac } from "node:crypto";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

/**
 * A GitHub Enterprise stand-in on the host: the REST API under /api/v3 that MegooColab reads pull requests with
 * (backend/app/git/providers.py), for one repository `o/r`, with state the test changes. The stack reaches it as
 * http://host.docker.internal:<port> (deploy/docker-compose.yml extra_hosts).
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
  /** every API path asked for, in order */
  requests: string[];
  close(): Promise<void>;
};

const SHA = (n: number) => `${String(n).repeat(40)}`.slice(0, 40);

export async function startFakeGit(token: string): Promise<FakeGit> {
  const prs = new Map<number, FakePr>();
  const requests: string[] = [];
  const server: Server = createServer((req, res) => {
    const path = (req.url ?? "").split("?")[0];
    requests.push(path);
    const send = (status: number, body: unknown) => {
      res.writeHead(status, { "content-type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (req.headers.authorization !== `Bearer ${token}`) return send(401, { message: "Bad credentials" });
    if (path === "/api/v3/user") return send(200, { login: "fake-bot" });
    let m = /^\/api\/v3\/repos\/o\/r\/pulls\/(\d+)(\/reviews)?$/.exec(path);
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
  return {
    port,
    baseUrl: `http://host.docker.internal:${port}`,
    token,
    prs,
    requests,
    close: () => new Promise<void>((done) => server.close(() => done())),
  };
}

/** A GitHub `pull_request` webhook delivery for `o/r` #n, signed (X-Hub-Signature-256) with `secret`. */
export function pullRequestDelivery(n: number, secret: string): { body: string; headers: Record<string, string> } {
  const body = JSON.stringify({ action: "closed", number: n, pull_request: { number: n }, repository: { full_name: "o/r" } });
  const signature = `sha256=${createHmac("sha256", secret).update(body).digest("hex")}`;
  return {
    body,
    headers: { "content-type": "application/json", "X-GitHub-Event": "pull_request", "X-Hub-Signature-256": signature },
  };
}
