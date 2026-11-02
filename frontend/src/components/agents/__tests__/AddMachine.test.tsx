import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RunnerTab } from "@/components/agents/RunnerTab";

type Fetch = (url: string, init?: RequestInit) => Promise<Response>;

let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/settings/agents",
  useSearchParams: () => new URLSearchParams(search),
}));

const OTHER = { token_id: "t1", name: "Workstation", os: "windows", online: true, agents: [], tools: [], runner_version: "0.5.0" };
let online = false;
let made = false;
let others: unknown[] = [];
let fetchMock: ReturnType<typeof vi.fn<Fetch>>;
const machineCalls = () => fetchMock.mock.calls.filter(([u]) => u === "/api/hub/machines").length;

beforeEach(() => {
  search = "tab=runner";
  online = false;
  made = false;
  others = [];
  fetchMock = vi.fn<Fetch>(async (url, init) => {
    if (url === "/api/tokens" && init?.method === "POST") {
      made = true;
      return new Response(JSON.stringify({ token: { id: "t9", name: "Laptop" }, secret: "mgc_x" }), { status: 201 });
    }
    if (url === "/api/hub/machines") {
      // a token made a moment ago is a machine at once, not connected and with no OS yet
      const mine = made ? [{ token_id: "t9", name: "Laptop", os: online ? "linux" : null, online, agents: [], tools: [], runner_version: null }] : [];
      return new Response(JSON.stringify([...others, ...mine]));
    }
    return new Response("[]");
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const value = (label: string) => (screen.getByLabelText(label) as HTMLTextAreaElement).value;

function tree(onAddAgent: (m: string) => void, client: QueryClient) {
  return (
    <QueryClientProvider client={client}>
      <RunnerTab onAddAgent={onAddAgent} />
    </QueryClientProvider>
  );
}

function show(onAddAgent = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { rerender } = render(tree(onAddAgent, client));
  return { onAddAgent, again: () => rerender(tree(onAddAgent, client)) };
}

async function makeToken() {
  await userEvent.type(await screen.findByLabelText("Machine name"), "Laptop");
  await userEvent.click(screen.getByRole("button", { name: "Make token" }));
}

describe("AddMachine", () => {
  it("makes a runner token and fills it into the sign-in command", async () => {
    show();
    await screen.findByLabelText("Machine name");
    expect(value("Sign in")).toContain("--token <make the token in step 1>");
    await makeToken();
    await waitFor(() => expect(value("Sign in")).toBe(`megoocolab-runner login --url ${window.location.origin} --token mgc_x`));
    const post = fetchMock.mock.calls.find(([u, init]) => u === "/api/tokens" && init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ name: "Laptop", scopes: ["runner"], expires_in_days: null });
    expect(screen.getByText("The token is shown only now. If you leave this page, make another.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Make token" })).toBeNull();
  });

  it("walks through install, check and keeping it running", async () => {
    show();
    await screen.findByLabelText("Machine name");
    await userEvent.click(screen.getByRole("button", { name: "Windows" }));
    expect(value("Install the runner")).toContain("scoop install");
    expect(value("Check it's ready")).toBe("megoocolab-runner doctor");
    expect(value("Turn it on: register it and start it now")).toBe("megoocolab-runner service install; megoocolab-runner service start");
    expect(value("Or start it in this terminal")).toBe("megoocolab-runner run");
    await userEvent.click(screen.getByRole("button", { name: "Linux / macOS" }));
    expect(value("Linux: keep it running after you sign out")).toBe("loginctl enable-linger $USER");
  });

  it("tells OMP users how to install OMP and sign in, for their platform", async () => {
    show();
    await screen.findByLabelText("Machine name");
    await userEvent.click(screen.getByRole("button", { name: "Windows" }));
    expect(value("OMP agents only: install OMP")).toBe("irm https://omp.sh/install.ps1 | iex");
    expect(value("OMP agents only: sign in to your model providers")).toBe("omp auth-broker login");
    await userEvent.click(screen.getByRole("button", { name: "Linux / macOS" }));
    expect(value("OMP agents only: install OMP")).toBe("curl -fsSL https://omp.sh/install | sh");
  });

  it("waits for the runner, then offers to add an agent on it", async () => {
    const { onAddAgent } = show();
    await makeToken();
    expect(await screen.findByText("Waiting for the runner to connect…")).toBeInTheDocument();
    online = true;
    await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument(), { timeout: 5_000 });
    await userEvent.click(screen.getByRole("button", { name: "Add an agent on it" }));
    expect(onAddAgent).toHaveBeenCalledWith("t9");
  });

  it("the first machine's token stays while its runner connects", async () => {
    show();
    await makeToken();
    // the new token is now the only machine: the steps must stay, with the token in them
    await waitFor(() => expect(machineCalls()).toBeGreaterThanOrEqual(2));
    expect(await screen.findByText("Waiting for the runner to connect…")).toBeInTheDocument();
    expect(value("Sign in")).toContain("--token mgc_x");
  });

  it("a token being set up survives looking at another machine", async () => {
    others = [OTHER];
    search = "tab=runner&machine=new";
    const { again } = show();
    await makeToken();
    await waitFor(() => expect(value("Sign in")).toContain("--token mgc_x"));
    search = "tab=runner&machine=t1";
    again();
    expect(await screen.findByRole("region", { name: "Workstation" })).toBeInTheDocument();
    search = "tab=runner&machine=new";
    again();
    await waitFor(() => expect(value("Sign in")).toContain("--token mgc_x"));
  });

  it("stops asking for the machines once the runner has connected", async () => {
    show();
    await makeToken();
    online = true;
    await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument(), { timeout: 5_000 });
    const calls = machineCalls();
    await new Promise((r) => setTimeout(r, 3_500));
    expect(machineCalls()).toBe(calls);
  }, 15_000);
});
