import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("api", () => {
  const assign = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    Object.defineProperty(window, "location", {
      value: { ...window.location, pathname: "/projects/PAY/board", search: "?x=1", assign },
      writable: true,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    assign.mockReset();
  });

  it("sends the client header, credentials and JSON body", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, { ok: true }));
    const result = await api<{ ok: boolean }>("/api/x", { method: "POST", json: { a: 1 } });
    expect(result).toEqual({ ok: true });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/x");
    expect(init?.credentials).toBe("include");
    const headers = new Headers(init?.headers);
    expect(headers.get("X-Megoo-Client")).toBe("web");
    expect(headers.get("content-type")).toBe("application/json");
    expect(init?.body).toBe(JSON.stringify({ a: 1 }));
  });

  it("returns undefined for 204", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api("/api/x", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("throws ApiError carrying the server detail", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(409, { detail: "project_key_taken" }));
    const err = (await api("/api/x").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.detail).toBe("project_key_taken");
  });

  it("redirects to login with next on 401", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(401, { detail: "not_authenticated" }));
    await api("/api/x").catch(() => undefined);
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fprojects%2FPAY%2Fboard%3Fx%3D1");
  });

  it("does not redirect on 401 from an auth page", async () => {
    window.location.pathname = "/login";
    vi.mocked(fetch).mockResolvedValue(jsonResponse(401, { detail: "invalid_credentials" }));
    await api("/api/auth/login", { method: "POST", json: {} }).catch(() => undefined);
    expect(assign).not.toHaveBeenCalled();
  });

  it("redirects to change-password when required", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(403, { detail: "password_change_required" }));
    await api("/api/teams").catch(() => undefined);
    expect(assign).toHaveBeenCalledWith("/change-password");
  });

  it("reads retry_after from a 429", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(429, { detail: "rate_limited", retry_after: 840 }));
    const err = await api("/api/x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(429);
    expect((err as ApiError).retryAfter).toBe(840);
  });
});
