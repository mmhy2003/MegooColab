"use client";

import { useId, useState } from "react";

import { Button } from "@/components/ui/Button";

export const MAX_RUNS = 3;

export const RUNS_HELP =
  "How many tasks and chats this agent works on at the same time, 1 to 3. Each is its own Claude Code, Codex or OMP session, so more runs use more of your machine and your plan's limits. You can change it later.";

/** The whole number typed, if it is 1 to MAX_RUNS. */
export function parseRuns(text: string): number | null {
  if (!/^\d+$/.test(text.trim())) return null;
  const n = Number(text);
  return n >= 1 && n <= MAX_RUNS ? n : null;
}

/** What an agent's card says next to its status while it runs; null while it runs nothing. */
export function runsLabel(running: number, max: number): string | null {
  if (running === 0) return null;
  return running > max ? `${running} running, limit ${max}` : `${running} of ${max} running`;
}

const STEP = "h-9 w-9 text-base text-cyan-ink hover:bg-surface disabled:cursor-not-allowed disabled:opacity-40";

/** A whole number from 1 to MAX_RUNS: typed, or stepped with – and +. */
export function RunsInput({ value, onChange }: { value: string; onChange: (text: string) => void }) {
  const id = useId();
  const n = parseRuns(value);
  const step = (by: number) => onChange(String(Math.min(MAX_RUNS, Math.max(1, (n ?? 1) + by))));
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs tracking-wider text-muted-foreground uppercase">
        Runs at once
      </label>
      <div className="inline-flex w-fit items-center overflow-hidden rounded border border-line bg-surface-2 focus-within:border-cyan">
        <button type="button" aria-label="Fewer runs at once" className={STEP} disabled={n !== null && n <= 1} onClick={() => step(-1)}>
          –
        </button>
        <input
          id={id}
          type="number"
          inputMode="numeric"
          min={1}
          max={MAX_RUNS}
          step={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={n === null ? true : undefined}
          className="w-12 bg-transparent text-center text-sm text-fg focus:outline-none"
        />
        <button type="button" aria-label="More runs at once" className={STEP} disabled={n !== null && n >= MAX_RUNS} onClick={() => step(1)}>
          +
        </button>
      </div>
      {n === null && <p className="text-xs text-pink">Choose a whole number from 1 to {MAX_RUNS}.</p>}
    </div>
  );
}

/** An agent's runs at once, raised or lowered any time; runs already going finish as they are. */
export function RunsField({ max, running, onSave }: { max: number; running: number; onSave: (runs: number) => Promise<void> | void }) {
  const [text, setText] = useState(String(max));
  const n = parseRuns(text);
  const until = max === 1 ? "they have finished" : `fewer than ${max} are running`;
  return (
    <div className="space-y-1">
      <div className="flex items-end gap-2">
        <RunsInput value={text} onChange={setText} />
        <Button variant="ghost" aria-label="Save runs at once" disabled={n === null || n === max} onClick={() => n !== null && onSave(n)}>
          Save
        </Button>
      </div>
      {running > max ? (
        <p role="status" className="text-xs text-amber">
          {running} runs are going now. They finish as they are; nothing new starts until {until}.
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          {max === 1 ? "One task or chat at a time." : `Up to ${max} tasks and chats at the same time.`}
        </p>
      )}
    </div>
  );
}
