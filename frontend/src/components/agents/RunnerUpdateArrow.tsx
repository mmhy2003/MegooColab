"use client";

import { RUNNER_INSTALL } from "@/components/agents/RunnerSetup";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/shadcn/popover";
import { Hint } from "@/components/ui/Hint";
import { useMe } from "@/lib/me";
import type { RunnerInfo } from "@/lib/types";
import { useUpdates } from "@/lib/updates";
import { isNewer } from "@/lib/versions";

const WINDOWS_UPDATE = "scoop update megoocolab-runner";

/** An amber ↑ next to an agent's status while its runner is older than the latest runner release: the details
 * on hover or focus, and on a click or tap (phones have no hover). Offline agents and local builds get none. */
export function RunnerUpdateArrow({ runner, ownerId }: { runner?: RunnerInfo | null; ownerId: string }) {
  const latest = useUpdates().data?.runner?.latest;
  const mine = useMe().data?.id === ownerId;
  if (!runner || !latest || !isNewer(latest, runner.version)) return null;
  const summary = mine
    ? `Runner update: you have ${runner.version}, ${latest} is out.`
    : `Runner update: this agent's runner is ${runner.version}, ${latest} is out. Its owner can update it.`;
  const command = runner.os === "windows" ? WINDOWS_UPDATE : RUNNER_INSTALL.unix;
  return (
    <Popover>
      <Hint label={summary}>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label="Runner update available"
            onClick={(e) => e.stopPropagation()} // on a task card, the click must not open the task
            className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-amber/50 bg-amber/15 text-[11px] leading-none font-black text-amber"
          >
            ↑
          </button>
        </PopoverTrigger>
      </Hint>
      <PopoverContent align="start" collisionPadding={8} className="w-72 max-w-[calc(100vw-1rem)] space-y-2 p-3 text-xs">
        <p>{summary}</p>
        {mine && (
          <>
            <p className="text-muted-foreground">Update with:</p>
            <code className="block rounded bg-surface-2 px-2 py-1 break-all">{command}</code>
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}
