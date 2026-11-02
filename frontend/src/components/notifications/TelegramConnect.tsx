"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { notificationKeys } from "@/lib/notifications";
import { telegramKeys, useMyTelegram } from "@/lib/telegram";

// how often to look whether Start was pressed, while waiting for it
const WAIT_MS = 3_000;

/** Linking this person's own Telegram chat: a one-time Start link opens the site's bot in Telegram. Shown only
 * while the site has a bot. */
export function TelegramConnect() {
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState(false);
  // asks again while waiting for Start, and stops once the chat is linked
  const mine = useMyTelegram(waiting ? (q) => (q.state.data?.linked ? false : WAIT_MS) : false);
  const linked = mine.data?.linked ?? false;
  const polling = waiting && !linked;

  useEffect(() => {
    // linking the first time turned Telegram on for some kinds
    if (waiting && linked) void client.invalidateQueries({ queryKey: notificationKeys.prefs() });
  }, [waiting, linked, client]);

  if (!mine.data?.available) return null;
  return (
    <section aria-labelledby="telegram-heading" className="card mb-4 max-w-xl space-y-2 p-4">
      <h2 id="telegram-heading" className="text-sm font-bold">Telegram</h2>
      {linked ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="flex-1 text-sm text-green-ink">Connected to Telegram</p>
          <Button
            variant="ghost"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              setWaiting(false);
              try {
                await api("/api/me/telegram", { method: "DELETE" });
                await client.invalidateQueries({ queryKey: telegramKeys.all });
              } catch (err) {
                setError(errorMessage(err));
              } finally {
                setBusy(false);
              }
            }}
          >
            Disconnect Telegram
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">Get your notifications from @{mine.data.bot_username} in Telegram.</p>
          <Button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                const { url } = await api<{ url: string }>("/api/me/telegram/link", { method: "POST" });
                window.open(url, "_blank", "noopener");
                setWaiting(true);
              } catch (err) {
                setError(errorMessage(err));
              } finally {
                setBusy(false);
              }
            }}
          >
            Connect Telegram
          </Button>
          {polling && <p role="status" className="text-sm text-muted-foreground">Waiting for you to press Start in Telegram…</p>}
        </div>
      )}
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
    </section>
  );
}
