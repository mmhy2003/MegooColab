"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import {
  type PushDevice,
  type PushState,
  pushKeys,
  pushSupport,
  thisDeviceEndpoint,
  turnOffPush,
  turnOnPush,
} from "@/lib/push";

const noChanges = () => () => undefined;

/** A browser-only value, read after hydration (null while rendering on the server). */
function useBrowser<T>(read: () => T): T | null {
  return useSyncExternalStore(noChanges, read, () => null);
}

const BLOCKED = "Your browser blocks notifications from MegooColab. Allow them in this site's settings, then reload the page.";

/** Push for the device in use (turn on / off), and the person's other devices that get it. */
export function PushDevices() {
  const client = useQueryClient();
  const support = useBrowser(pushSupport);
  const denied = useBrowser(() => support === "supported" && Notification.permission === "denied");
  const devices = useQuery({ queryKey: pushKeys.subscriptions(), queryFn: () => api<PushDevice[]>("/api/push/subscriptions") });
  const endpoint = useQuery({ queryKey: pushKeys.thisDevice(), queryFn: thisDeviceEndpoint, enabled: support === "supported" });
  const [refused, setRefused] = useState(false); // permission refused after a click, in this visit
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (support === null) return null;

  const mine = devices.data?.find((d) => d.endpoint === endpoint.data);
  const others = devices.data?.filter((d) => d !== mine) ?? [];
  const state: PushState = support !== "supported" ? support : denied || refused ? "blocked" : mine ? "on" : "off";
  const refresh = () => client.invalidateQueries({ queryKey: pushKeys.all });
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      await refresh();
    }
  };

  return (
    <section className="card mb-4 max-w-xl space-y-3 p-4 text-sm">
      <ThisDevice
        state={state}
        busy={busy}
        onTurnOn={() =>
          run(async () => {
            if ((await turnOnPush()) === "blocked") setRefused(true);
          })
        }
        onTurnOff={() => mine && run(() => turnOffPush(mine.id))}
      />
      {error && <p role="alert" className="text-pink">{error}</p>}
      {others.length > 0 && (
        <div className="border-t border-line pt-3">
          <p className="mb-1 text-xs text-muted-foreground">Other devices getting push</p>
          <ul className="space-y-1">
            {others.map((d) => (
              <li key={d.id} className="flex items-center justify-between gap-2">
                <span>{d.name} · since {new Date(d.created_at).toLocaleDateString()}</span>
                <Button
                  variant="ghost"
                  aria-label={`Remove ${d.name}`}
                  disabled={busy}
                  onClick={() => run(() => api(`/api/push/subscriptions/${d.id}`, { method: "DELETE" }))}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function ThisDevice({ state, busy, onTurnOn, onTurnOff }: { state: PushState; busy: boolean; onTurnOn: () => void; onTurnOff: () => void }) {
  if (state === "unsupported") return <p className="text-muted-foreground">This browser can&apos;t receive push notifications.</p>;
  if (state === "ios-install") {
    return (
      <p className="text-muted-foreground">
        On iPhone and iPad, add MegooColab to your Home Screen (Share → Add to Home Screen) and open it from there to turn on push.
      </p>
    );
  }
  if (state === "blocked") return <p className="text-pink">{BLOCKED}</p>;
  const on = state === "on";
  return (
    <div className="flex items-center justify-between gap-3">
      <div>
        <p className="font-semibold">{on ? "Push is on for this device" : "Push is off on this device"}</p>
        {!on && <p className="text-xs text-muted-foreground">Turn it on to get notifications here even when MegooColab is closed.</p>}
      </div>
      <Button variant={on ? "ghost" : "primary"} disabled={busy} onClick={on ? onTurnOff : onTurnOn}>
        {on ? "Turn off" : "Turn on"}
      </Button>
    </div>
  );
}
