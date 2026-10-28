import { expect, type APIRequestContext } from "@playwright/test";

/** MCP tools/call with a bearer token; returns the tool's result (or throws its error text). */
export async function tool<T = Record<string, unknown>>(
  request: APIRequestContext,
  token: string,
  name: string,
  args: Record<string, unknown>,
): Promise<T> {
  const r = await request.post("/api/mcp", {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json, text/event-stream", "Content-Type": "application/json" },
    data: { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } },
  });
  expect(r.ok()).toBeTruthy();
  const result = (await r.json()).result;
  const text: string = result.content?.[0]?.text ?? "";
  if (result.isError) throw new Error(`${name}: ${text}`);
  const structured = result.structuredContent;
  return (structured ? (structured.result ?? structured) : JSON.parse(text)) as T;
}
