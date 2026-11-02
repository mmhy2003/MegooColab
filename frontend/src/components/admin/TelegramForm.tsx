"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { telegramKeys, useAdminTelegram } from "@/lib/telegram";

/** The site's one Telegram bot: its token is checked with Telegram when saved, and never shown again. */
export function TelegramForm() {
  const client = useQueryClient();
  const bot = useAdminTelegram();
  const { ask, dialog } = useConfirm();
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: telegramKeys.all });

  if (bot.isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  const username = bot.data?.bot_username;
  return (
    <div className="card space-y-4 p-4">
      {dialog}
      <p className="text-sm text-muted-foreground">
        People can then connect their own Telegram in Settings › Notifications and choose what reaches them there.
      </p>
      {username ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="flex-1 text-sm">Connected to @{username}.</p>
          <Button
            variant="danger"
            disabled={busy}
            onClick={async () => {
              if (!(await ask({ tone: "danger", title: "Remove the bot?", text: "Telegram notifications stop for everyone.", ok: "Remove" }))) return;
              setBusy(true);
              setError(null);
              try {
                await api("/api/admin/telegram", { method: "DELETE" });
                await refresh();
              } catch (err) {
                setError(errorMessage(err));
              } finally {
                setBusy(false);
              }
            }}
          >
            Remove
          </Button>
        </div>
      ) : (
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError(null);
            try {
              await api("/api/admin/telegram", { method: "PUT", json: { token: token.trim() } });
              setToken("");
              await refresh();
            } catch (err) {
              setError(errorMessage(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            <li>In Telegram, open @BotFather and send /newbot.</li>
            <li>Pick a name and a username for the bot.</li>
            <li>Paste the token it gives you here.</li>
          </ol>
          <Input label="Bot token" type="password" autoComplete="off" required maxLength={200} value={token} onChange={(e) => setToken(e.target.value)} />
          <Button type="submit" disabled={busy || !token.trim()}>Save</Button>
        </form>
      )}
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
    </div>
  );
}
