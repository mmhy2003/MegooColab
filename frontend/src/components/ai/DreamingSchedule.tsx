"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { saveAdminSettings } from "@/lib/adminSettings";
import { errorMessage } from "@/lib/errors";
import type { AdminSettings } from "@/lib/types";

/** The nightly dreaming run: on or off, and its hour (empty: the server's own setting). */
export function DreamingSchedule({ settings }: { settings: AdminSettings }) {
  const client = useQueryClient();
  const [enabled, setEnabled] = useState(settings.dreaming.enabled);
  const [hour, setHour] = useState(settings.dreaming.hour_utc == null ? "" : String(settings.dreaming.hour_utc));
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <form
      className="card space-y-3 p-4"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await saveAdminSettings(client, settings, { dreaming: { enabled, hour_utc: hour === "" ? null : Number(hour) } });
          setStatus({ ok: true, text: "Saved." });
        } catch (err) {
          setStatus({ ok: false, text: errorMessage(err) });
        }
      }}
    >
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Run dreaming every night
      </label>
      <Input
        label="Dreaming hour (UTC)"
        type="number"
        min={0}
        max={23}
        placeholder="The server's setting"
        value={hour}
        onChange={(e) => setHour(e.target.value)}
      />
      {status && <p role="status" className={`text-sm ${status.ok ? "text-green-ink" : "text-pink"}`}>{status.text}</p>}
      <Button type="submit">Save</Button>
    </form>
  );
}
