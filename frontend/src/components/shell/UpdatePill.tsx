"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/shadcn/popover";
import { useUpdates } from "@/lib/updates";

const HOW_TO_UPDATE = "https://github.com/mmhy2003/MegooColab/blob/main/docs/install.md#12-upgrades";

/** A quiet "Update" pill in the header while a newer MegooColab is out. The server sends it to admins only:
 * they are the ones who can install it. It never opens by itself and stays until the server is updated. */
export function UpdatePill() {
  const app = useUpdates().data?.app;
  if (!app) return null;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Update available: MegooColab ${app.latest}`}
          className="rounded-full bg-cyan px-2.5 py-0.5 text-xs font-bold text-on-accent hover:opacity-90"
        >
          Update
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" collisionPadding={8} className="w-64 space-y-1 p-3 text-sm">
        <p className="font-semibold">MegooColab {app.latest}</p>
        <p className="text-muted-foreground">You&apos;re on {app.current}.</p>
        <div className="flex gap-3 pt-1 text-xs">
          <a href={app.url} target="_blank" rel="noreferrer">What&apos;s new</a>
          <a href={HOW_TO_UPDATE} target="_blank" rel="noreferrer">How to update</a>
        </div>
      </PopoverContent>
    </Popover>
  );
}
