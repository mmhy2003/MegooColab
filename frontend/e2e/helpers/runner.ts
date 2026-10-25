import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { mkdirSync } from "node:fs";
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

/** Logs the runner in with an isolated config, then runs it. Resolves once the process is running. */
export function startRunner(opts: StartRunnerOptions): RunnerHandle {
  const env = {
    ...isolatedEnv(opts.home),
    MEGOO_ADAPTER_CLAUDE_CODE: `"${opts.adapterOverride}"`,
    FAKEAGENT_SCENARIO: JSON.stringify(opts.scenario),
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
  const exited = new Promise<void>((done) => child.once("exit", () => done()));

  return {
    output: () => log,
    async stop() {
      if (child.exitCode !== null || child.pid === undefined) return;
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
