"use client";

import { useEffect, useState } from "react";

import { previewSchedule, type SchedulePreview } from "@/lib/crons";

const PRESETS: { label: string; expr: string; time?: boolean }[] = [
  { label: "Every hour", expr: "0 * * * *" },
  { label: "Every day at…", expr: "0 9 * * *", time: true },
  { label: "Weekdays at…", expr: "0 9 * * 1-5", time: true },
  { label: "Every Monday at…", expr: "0 9 * * 1", time: true },
  { label: "1st of the month", expr: "0 9 1 * *", time: true },
];
const PARTS = ["minute", "hour", "day of month", "month", "day of week"];
const DEBOUNCE_MS = 300;

/** A cron expression, written by hand or from a preset, checked by the server as it is typed (the one set of rules):
 * what is wrong in plain words, or what it means and when it next runs. */
export function ScheduleField({
  value,
  timezone,
  onChange,
  onValid,
}: {
  value: string;
  timezone: string;
  onChange: (expr: string) => void;
  onValid: (ok: boolean) => void;
}) {
  // the server's answer, with the expression and zone it is for: shown only while they are still what is typed
  const [answer, setPreview] = useState<{ expr: string; tz: string; preview: SchedulePreview } | null>(null);
  const preview = answer && answer.expr === value.trim() && answer.tz === timezone ? answer.preview : null;
  const fields = value.trim().split(/\s+/);
  const timed = /^\d{1,2} \d{1,2} /.test(value.trim());

  useEffect(() => {
    onValid(false); // until the server has checked what is typed now
    if (!value.trim()) return;
    let live = true;
    const t = setTimeout(async () => {
      try {
        const p = await previewSchedule(value.trim(), timezone);
        if (!live) return;
        setPreview({ expr: value.trim(), tz: timezone, preview: p });
        onValid(p.ok);
      } catch {
        if (live) onValid(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      live = false;
      clearTimeout(t);
    };
    // onValid is the parent's setter: a new one each render must not re-ask the server
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, timezone]);

  const setTime = (hhmm: string) => {
    const [h, m] = hhmm.split(":").map(Number);
    if (Number.isNaN(h) || Number.isNaN(m)) return;
    onChange([String(m), String(h), ...fields.slice(2)].join(" "));
  };
  const time = timed ? `${fields[1].padStart(2, "0")}:${fields[0].padStart(2, "0")}` : "";

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => onChange(p.expr)}
            className={`rounded-full border px-2 text-xs ${value.trim() === p.expr ? "border-cyan text-cyan-ink" : "border-line text-muted-foreground"}`}
          >
            {p.label}
          </button>
        ))}
        {timed && (
          <label className="flex items-center gap-1 text-xs text-muted-foreground">
            at
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)}
              className="rounded border border-line bg-surface-2 px-1 text-xs" />
          </label>
        )}
      </div>
      <label htmlFor="cron-schedule" className="block text-xs tracking-wider text-muted-foreground uppercase">
        Schedule
      </label>
      <input
        id="cron-schedule"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="0 2 * * *"
        className="w-full rounded border border-line bg-surface-2 px-2 py-1 font-mono text-sm"
        aria-invalid={preview?.ok === false || undefined}
      />
      <div className="grid grid-cols-5 gap-1 text-center">
        {PARTS.map((part, i) => (
          <div key={part} className="min-w-0 rounded border border-line bg-surface-2 px-1 py-0.5">
            <span className="block truncate font-mono text-sm text-cyan-ink">{fields[i] || "–"}</span>
            <span className="block truncate text-[10px] text-muted-foreground">{part}</span>
          </div>
        ))}
      </div>
      {preview?.ok === false && <p className="text-xs text-pink">{preview.error}</p>}
      {preview?.ok && (
        <div className="rounded-r border-l-4 border-green bg-green/5 px-3 py-1.5 text-sm">
          <b>{preview.description}</b> <span className="text-muted-foreground">({timezone})</span>
          <p className="text-xs text-muted-foreground">
            Next runs:{" "}
            {preview.next
              .map((t) => new Date(t).toLocaleString(undefined, { timeZone: timezone, weekday: "short", day: "numeric",
                month: "short", hour: "2-digit", minute: "2-digit" }))
              .join(" · ")}
          </p>
        </div>
      )}
    </div>
  );
}
