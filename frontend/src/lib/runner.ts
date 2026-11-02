/** The runner's commands and where to get it, per platform. */

export type Platform = "windows" | "unix";

// the runner's releases only: the newest release of all may be a MegooColab one (tagged v…)
export const RELEASES = "https://github.com/mmhy2003/MegooColab/releases?q=runner-v&expanded=true";
export const RUNNER_INSTALL: Record<Platform, string> = {
  windows: "scoop install https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/scoop/megoocolab-runner.json",
  unix: "curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh",
};
// OMP serves ACP itself: OMP agents need it installed and signed in on the machine (Node is not needed for them)
export const OMP_INSTALL: Record<Platform, string> = {
  windows: "irm https://omp.sh/install.ps1 | iex",
  unix: "curl -fsSL https://omp.sh/install | sh",
};
// re-running the install script replaces the binary in place
export const RUNNER_UPDATE: Record<Platform, string> = {
  windows: "scoop update megoocolab-runner",
  unix: RUNNER_INSTALL.unix,
};

export const R = "megoocolab-runner";

export function detectPlatform(): Platform {
  return typeof navigator !== "undefined" && /win/i.test(navigator.platform) ? "windows" : "unix";
}

/** A machine's platform from the OS its runner reported (windows, linux, macos); null when it never said. */
export function platformOf(os: string | null | undefined): Platform | null {
  if (os === "windows") return "windows";
  return os === "linux" || os === "macos" ? "unix" : null;
}

/** Two commands on one line: PowerShell 5.1 (Scoop's shell) has no &&. */
export function both(platform: Platform, first: string, second: string) {
  return `${first}${platform === "windows" ? "; " : " && "}${second}`;
}

/** This server's sign-in command, with a token or a placeholder for one. */
export function loginCommand(token: string) {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return `${R} login --url ${origin} --token ${token}`;
}
