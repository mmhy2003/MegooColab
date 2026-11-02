"use client";

import type { Platform } from "@/lib/runner";

/** Windows or Linux / macOS, for the commands shown under it. */
export function PlatformToggle({ value, onChange }: { value: Platform; onChange: (p: Platform) => void }) {
  return (
    <div className="flex gap-2" role="group" aria-label="Platform">
      {(["windows", "unix"] as const).map((p) => (
        <button
          key={p}
          type="button"
          aria-pressed={value === p}
          onClick={() => onChange(p)}
          className={`rounded border px-3 py-1 text-xs ${value === p ? "border-cyan text-cyan-ink" : "border-line text-muted-foreground"}`}
        >
          {p === "windows" ? "Windows" : "Linux / macOS"}
        </button>
      ))}
    </div>
  );
}
