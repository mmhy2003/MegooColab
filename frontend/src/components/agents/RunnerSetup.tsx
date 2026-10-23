"use client";

import { useState } from "react";

import { Snippet } from "@/components/agents/Snippet";

type Platform = "windows" | "unix";

const RELEASES = "https://github.com/mmhy2003/MegooColab/releases/latest";
const INSTALL: Record<Platform, string> = {
  windows: "scoop install https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/scoop/megoocolab-runner.json",
  unix: "curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh",
};

function detectPlatform(): Platform {
  return typeof navigator !== "undefined" && /win/i.test(navigator.platform) ? "windows" : "unix";
}

export function RunnerSetup() {
  const [platform, setPlatform] = useState<Platform>(detectPlatform);
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        The runner is a small program on your computer that starts your agents when a task is assigned to them. Your code never leaves your machine.
      </p>
      <div className="flex gap-2" role="group" aria-label="Platform">
        {(["windows", "unix"] as const).map((p) => (
          <button
            key={p}
            type="button"
            aria-pressed={platform === p}
            onClick={() => setPlatform(p)}
            className={`rounded border px-3 py-1 text-xs ${platform === p ? "border-cyan text-cyan-ink" : "border-line text-muted"}`}
          >
            {p === "windows" ? "Windows" : "Linux / macOS"}
          </button>
        ))}
      </div>
      <Snippet label="1. Install" value={INSTALL[platform]} />
      <p className="text-xs text-muted">
        Or <a href={RELEASES} target="_blank" rel="noreferrer">download it from GitHub</a>.
      </p>
      <Snippet label="2. Sign in" value={`megoocolab-runner login --url ${origin} --token <paste a runner token>`} />
      <p className="text-xs text-muted">Create the runner token under Access tokens, with the Runner scope.</p>
      <Snippet label="3. Start" value="megoocolab-runner run" />
      <Snippet label="4. Keep it running in the background (optional)" value="megoocolab-runner service install" />
    </div>
  );
}
