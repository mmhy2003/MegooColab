"use client";

import { useState } from "react";

import { Snippet } from "@/components/agents/Snippet";
import { TabPanel, Tabs } from "@/components/ui/Tabs";

type Platform = "windows" | "unix";
// prefixed: the tab and panel ids must not clash with other tabs on the page
type Tab = "runner-setup" | "runner-background" | "runner-update" | "runner-troubleshoot";

// the runner's releases only: the newest release of all may be a MegooColab one (tagged v…)
const RELEASES = "https://github.com/mmhy2003/MegooColab/releases?q=runner-v&expanded=true";
export const RUNNER_INSTALL: Record<Platform, string> = {
  windows: "scoop install https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/scoop/megoocolab-runner.json",
  unix: "curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh",
};
// re-running the install script replaces the binary in place
export const RUNNER_UPDATE: Record<Platform, string> = {
  windows: "scoop update megoocolab-runner",
  unix: RUNNER_INSTALL.unix,
};

const TABS: { id: Tab; label: string }[] = [
  { id: "runner-setup", label: "Set up" },
  { id: "runner-background", label: "Keep it running" },
  { id: "runner-update", label: "Update" },
  { id: "runner-troubleshoot", label: "Troubleshoot" },
];

const R = "megoocolab-runner";

function detectPlatform(): Platform {
  return typeof navigator !== "undefined" && /win/i.test(navigator.platform) ? "windows" : "unix";
}

/** Two commands on one line: PowerShell 5.1 (Scoop's shell) has no &&. */
function both(platform: Platform, first: string, second: string) {
  return `${first}${platform === "windows" ? "; " : " && "}${second}`;
}

/** Setting up the runner and every command for it day to day. Opens on Set up until there are agents, then on
 * Keep it running, unless a tab has been chosen. */
export function RunnerSetup({ hasAgents }: { hasAgents?: boolean }) {
  const [platform, setPlatform] = useState<Platform>(detectPlatform);
  const [chosen, setChosen] = useState<Tab | null>(null);
  const tab = chosen ?? (hasAgents ? "runner-background" : "runner-setup");
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const login = `${R} login --url ${origin} --token <paste a runner token>`;
  const note = "text-xs text-muted-foreground";
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        The runner is a small program on your computer that starts your agents when a task is assigned to them. Your code never leaves your machine.
      </p>
      <div className="flex gap-2" role="group" aria-label="Platform">
        {(["windows", "unix"] as const).map((p) => (
          <button
            key={p}
            type="button"
            aria-pressed={platform === p}
            onClick={() => setPlatform(p)}
            className={`rounded border px-3 py-1 text-xs ${platform === p ? "border-cyan text-cyan-ink" : "border-line text-muted-foreground"}`}
          >
            {p === "windows" ? "Windows" : "Linux / macOS"}
          </button>
        ))}
      </div>
      <Tabs label="Runner" tabs={TABS} value={tab} onChange={setChosen} />

      <TabPanel id="runner-setup" active={tab === "runner-setup"}>
        <div className="space-y-4">
          <Snippet label="1. Install" value={RUNNER_INSTALL[platform]} />
          <p className={note}>
            Or <a href={RELEASES} target="_blank" rel="noreferrer">download it from GitHub</a>.
          </p>
          <Snippet label="2. Sign in" value={login} />
          <p className={note}>Create the runner token under Access tokens, with the Runner scope.</p>
          <p className={note}>Create one token per computer, and link each agent to the token of the computer it runs on.</p>
          <Snippet label="3. Check it's ready" value={`${R} doctor`} />
          <Snippet label="4. Start it in this terminal" value={`${R} run`} />
          <p className={note}>It stops when you close the terminal. To keep it running without one, see Keep it running.</p>
        </div>
      </TabPanel>

      <TabPanel id="runner-background" active={tab === "runner-background"}>
        <div className="space-y-4">
          <p className={note}>
            The runner runs in the background as you, and starts again every time you sign in to this computer. No admin rights needed.
          </p>
          <Snippet label="Turn it on: register it and start it now" value={both(platform, `${R} service install`, `${R} service start`)} />
          {platform === "unix" && <Snippet label="Linux: keep it running after you sign out" value="loginctl enable-linger $USER" />}
          <Snippet label="Is it running?" value={`${R} service status`} />
          <Snippet label="Stop it for now (it starts again at your next sign-in)" value={`${R} service stop`} />
          <Snippet label="Start it again" value={`${R} service start`} />
          <Snippet label="Turn it off (stop it and remove it from sign-in)" value={`${R} service uninstall`} />
        </div>
      </TabPanel>

      <TabPanel id="runner-update" active={tab === "runner-update"}>
        <div className="space-y-4">
          <Snippet label="1. Stop it, if it runs in the background" value={`${R} service stop`} />
          <Snippet label="2. Update" value={RUNNER_UPDATE[platform]} />
          <Snippet label="3. Start the new version" value={`${R} service start`} />
          <Snippet label="Check which version you have" value={`${R} version`} />
        </div>
      </TabPanel>

      <TabPanel id="runner-troubleshoot" active={tab === "runner-troubleshoot"}>
        <div className="space-y-4">
          <Snippet label="Check settings, server access and agents" value={`${R} doctor`} />
          {platform === "windows" ? (
            <Snippet label="Follow the background log" value="Get-Content -Tail 50 -Wait $env:LOCALAPPDATA\megoocolab\logs\runner.log" />
          ) : (
            <>
              <Snippet label="Follow the background log (Linux)" value="tail -f ~/.cache/megoocolab/logs/runner.log" />
              <Snippet label="Follow the background log (macOS)" value="tail -f ~/Library/Caches/megoocolab/logs/runner.log" />
            </>
          )}
          <Snippet label="Sign in again, then start it" value={both(platform, login, `${R} service start`)} />
          <p className={note}>For an agent that stays Offline after its token was revoked or replaced.</p>
        </div>
      </TabPanel>
    </div>
  );
}
