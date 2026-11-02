"use client";

import { useState } from "react";

import { PlatformToggle } from "@/components/agents/PlatformToggle";
import { Snippet } from "@/components/agents/Snippet";
import { both, detectPlatform, loginCommand, platformOf, R, RUNNER_UPDATE, type Platform } from "@/lib/runner";

const LOG: Record<string, string> = {
  windows: "Get-Content -Tail 50 -Wait $env:LOCALAPPDATA\\megoocolab\\logs\\runner.log",
  linux: "tail -f ~/.cache/megoocolab/logs/runner.log",
  macos: "tail -f ~/Library/Caches/megoocolab/logs/runner.log",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <h3 className="text-xs font-bold tracking-wider text-cyan-ink uppercase">{title}</h3>
      {children}
    </div>
  );
}

/** One machine's day-to-day runner commands, for the OS its runner reported (asked for when it never said). */
export function RunnerCommands({ os }: { os: string | null }) {
  const known = platformOf(os);
  const [picked, setPicked] = useState<Platform>(detectPlatform);
  const platform = known ?? picked;
  const note = "text-xs text-muted-foreground";
  return (
    <div className="space-y-5">
      {!known && <PlatformToggle value={picked} onChange={setPicked} />}
      <Section title="Keep it running">
        <p className={note}>
          The runner runs in the background as you, and starts again every time you sign in to this computer. No admin rights needed.
        </p>
        <Snippet label="Turn it on: register it and start it now" value={both(platform, `${R} service install`, `${R} service start`)} />
        {platform === "unix" && os !== "macos" && <Snippet label="Linux: keep it running after you sign out" value="loginctl enable-linger $USER" />}
        <Snippet label="Is it running?" value={`${R} service status`} />
        <Snippet label="Stop it for now (it starts again at your next sign-in)" value={`${R} service stop`} />
        <Snippet label="Start it again" value={`${R} service start`} />
        <Snippet label="Turn it off (stop it and remove it from sign-in)" value={`${R} service uninstall`} />
      </Section>
      <Section title="Update">
        <Snippet label="1. Stop it, if it runs in the background" value={`${R} service stop`} />
        <Snippet label="2. Update" value={RUNNER_UPDATE[platform]} />
        <Snippet label="3. Start the new version" value={`${R} service start`} />
        <Snippet label="Check which version you have" value={`${R} version`} />
      </Section>
      <Section title="Troubleshoot">
        <Snippet label="Check settings, server access and agents" value={`${R} doctor`} />
        {platform === "windows" ? (
          <Snippet label="Follow the background log" value={LOG.windows} />
        ) : os === "linux" || os === "macos" ? (
          <Snippet label="Follow the background log" value={LOG[os]} />
        ) : (
          <>
            <Snippet label="Follow the background log (Linux)" value={LOG.linux} />
            <Snippet label="Follow the background log (macOS)" value={LOG.macos} />
          </>
        )}
        <Snippet label="Sign in again, then start it" value={both(platform, loginCommand("<paste a runner token>"), `${R} service start`)} />
        <p className={note}>For an agent that stays Offline after its token was revoked or replaced.</p>
      </Section>
    </div>
  );
}
