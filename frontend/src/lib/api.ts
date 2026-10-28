export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    /** Seconds until a rate limit lets the call through again (429 only). */
    public retryAfter: number | null = null,
  ) {
    super(`${status} ${detail}`);
    this.name = "ApiError";
  }
}

const AUTH_PAGES = ["/login", "/setup", "/invite", "/reset", "/forgot", "/change-password"];

function onAuthPage(): boolean {
  const path = window.location.pathname;
  return AUTH_PAGES.some((p) => path === p || path.startsWith(`${p}/`));
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return "validation_error";
  }
  return fallback;
}

export async function api<T = unknown>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const { json, headers, ...rest } = init;
  const h = new Headers(headers);
  h.set("X-Megoo-Client", "web");
  let body = rest.body;
  if (json !== undefined) {
    h.set("content-type", "application/json");
    body = JSON.stringify(json);
  }
  const res = await fetch(path, { ...rest, body, headers: h, credentials: "include" });

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data: unknown = text ? safeJson(text) : undefined;
  if (res.ok) return data as T;

  const detail = detailOf(data, res.statusText || "error");
  if (typeof window !== "undefined") {
    if (res.status === 401 && !onAuthPage()) {
      const next = window.location.pathname + window.location.search;
      window.location.assign(`/login?next=${encodeURIComponent(next)}`);
    } else if (res.status === 403 && detail === "password_change_required" && !onAuthPage()) {
      window.location.assign("/change-password");
    }
  }
  throw new ApiError(res.status, detail, retryAfterOf(data));
}

function retryAfterOf(body: unknown): number | null {
  if (body && typeof body === "object" && "retry_after" in body) {
    const n = (body as { retry_after: unknown }).retry_after;
    if (typeof n === "number" && n > 0) return n;
  }
  return null;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}
