"use client";

import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/Button";
import { audioSupported, playChime, SOUND_KEY } from "@/lib/beep";
import { useStoredState } from "@/lib/stored";

const noChanges = () => () => undefined;

/** The per-browser switch for the chime played when a new notification arrives, with a button to hear it. */
export function SoundSetting() {
  const supported = useSyncExternalStore(noChanges, audioSupported, () => false);
  const [on, setOn] = useStoredState(SOUND_KEY, true, "local");
  if (!supported) return null;
  return (
    <section aria-label="Sound" className="card mb-4 max-w-xl space-y-3 p-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-40 flex-1">
          <p className="font-semibold">{on ? "Sound is on in this browser" : "Sound is off in this browser"}</p>
          <p className="text-xs text-muted-foreground">
            {on
              ? "A short chime plays when a new notification arrives while MegooColab is open."
              : "Turn it on to hear a short chime when a new notification arrives while MegooColab is open."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" onClick={playChime}>Play sound</Button>
          <Button variant={on ? "ghost" : "primary"} onClick={() => setOn(!on)}>
            {on ? "Turn off" : "Turn on"}
          </Button>
        </div>
      </div>
      <p className="border-t border-line pt-3 text-xs text-muted-foreground">
        Browsers allow sound only after you have clicked or typed in a tab, so a tab you just reloaded stays silent until then.
      </p>
    </section>
  );
}
