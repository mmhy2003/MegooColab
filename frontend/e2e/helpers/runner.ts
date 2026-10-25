import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

const WIN = process.platform === "win32";
const EXE = WIN ? ".exe" : "";
const REPO_ROOT = resolve(__dirname, "..", "..", "..");

export type Binaries = { runner: string; fakeAgent: string };

/** Builds the runner and the fake agent into `dir` (the Go toolchain must be on the PATH). */
export function buildBinaries(dir: string): Binaries {
  mkdirSync(dir, { recursive: true });
  const runner = join(dir, `megoocolab-runner${EXE}`);
  const fakeAgent = join(dir, `fakeagent${EXE}`);
  const cwd = join(REPO_ROOT, "runner");
  execFileSync("go", ["build", "-o", runner, "."], { cwd, stdio: "inherit" });
  execFileSync("go", ["build", "-o", fakeAgent, "./internal/fakeagent"], { cwd, stdio: "inherit" });
  return { runner, fakeAgent };
}

export type StartRunnerOptions = {
  url: string;
  token: string;
  /** Becomes the runner's whole user profile: config and cache both live under it. */
  home: string;
  /** Path to the fake agent executable (used as MEGOO_ADAPTER_CLAUDE_CODE). */
  adapterOverride: string;
  /** Steps for FAKEAGENT_SCENARIO. */
  scenario: unknown[];
  /** Path to the built megoocolab-runner. */
  runnerBin: string;
  /** Extra environment for the runner and so for the fake agent (FAKEAGENT_SESSIONS_DIR, FAKEAGENT_RESUME, ...). */
  env?: Record<string, string>;
};

export type RunnerHandle = { stop(): Promise<void>; output(): string };

/** The environment that points os.UserConfigDir and os.UserCacheDir at `home` on every OS. */
export function isolatedEnv(home: string): NodeJS.ProcessEnv {
  const config = join(home, "config");
  const cache = join(home, "cache");
  mkdirSync(config, { recursive: true });
  mkdirSync(cache, { recursive: true });
  return {
    ...process.env,
    HOME: home,
    USERPROFILE: home,
    APPDATA: config, // os.UserConfigDir on Windows
    LOCALAPPDATA: cache, // os.UserCacheDir on Windows
    XDG_CONFIG_HOME: config, // Linux
    XDG_CACHE_HOME: cache,
  };
}

/**
 * Logs the runner in with an isolated config, then starts `run` in the background and returns
 * its handle right away: it does not wait for the runner to connect (wait for "Online" in the UI).
 */
export function startRunner(opts: StartRunnerOptions): RunnerHandle {
  const env = {
    ...isolatedEnv(opts.home),
    MEGOO_ADAPTER_CLAUDE_CODE: `"${opts.adapterOverride}"`,
    FAKEAGENT_SCENARIO: JSON.stringify(opts.scenario),
    ...opts.env,
  };
  execFileSync(opts.runnerBin, ["login", "--url", opts.url, "--token", opts.token], { env, stdio: "pipe" });
  const child: ChildProcess = spawn(opts.runnerBin, ["run"], {
    env,
    stdio: ["ignore", "pipe", "pipe"],
    detached: !WIN, // own process group on POSIX so the whole tree can be signalled
    windowsHide: true,
  });
  let log = "";
  child.stdout?.on("data", (d) => (log += d));
  child.stderr?.on("data", (d) => (log += d));
  // a failed spawn (or kill) emits "error"; without a listener it would crash the test process
  child.on("error", (err) => (log += `\n[runner process error] ${err.message}\n`));
  const exited = new Promise<void>((done) => child.once("exit", () => done()));

  return {
    output: () => log,
    async stop() {
      // never started, or already exited (with a code, or by a signal)
      if (child.pid === undefined || child.exitCode !== null || child.signalCode !== null) return;
      try {
        if (WIN) execFileSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
        else process.kill(-child.pid, "SIGKILL");
      } catch {
        // already gone
      }
      await exited;
    },
  };
}

// ---- fake agent scenarios ------------------------------------------------------------------------

export type ScenarioStep = Record<string, unknown>;

export const say = (text: string): ScenarioStep => ({ say: text });

/** Steps that run only in a turn whose prompt contains `text`, so one scenario can drive many runs. */
export const onPrompt = (text: string, ...then: ScenarioStep[]): ScenarioStep => ({ if_prompt_contains: text, then });

/** A call of one of MegooColab's MCP tools, over the run's own MCP server and token. */
export const mcp = (tool: string, args: Record<string, unknown>): ScenarioStep => ({ mcp_call: { tool, args } });

/** What one fake agent process saw and did (runner/internal/fakeagent Report). */
export type FakeAgentReport = {
  cwd: string;
  prompts: string[] | null;
  session_events: string[] | null;
  steps: { type: string; ok?: boolean; error?: string; exists?: boolean; content?: string; tool?: string; result?: string }[];
};

/** Every report in a FAKEAGENT_REPORT_DIR (one per agent process, so one per run), oldest first. */
export function readReports(dir: string): FakeAgentReport[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => /^report-\d+-\d+\.json$/.test(f))
    // by the start time in ns (too big for a Number): as equal-length strings
    .sort((a, b) => (a.split("-")[1].padStart(24, "0") < b.split("-")[1].padStart(24, "0") ? -1 : 1))
    .map((f) => JSON.parse(readFileSync(join(dir, f), "utf8")) as FakeAgentReport);
}
