"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { COMMON_EFFORTS, effortName, modelKey } from "@/lib/agents";
import type { ModelOption } from "@/lib/types";

const OTHER = "__other";

export type ModelChoice = { model?: string | null; effort?: string | null };

/** The model an agent's runs start on (one it offered on its last run, or any name typed, such as "opus") and the
 * thinking effort, from the levels that model offers. */
export function ModelField({
  model,
  effort,
  knownModels,
  onSave,
}: {
  model: string | null;
  effort: string | null;
  knownModels: ModelOption[];
  onSave: (choice: ModelChoice) => Promise<void> | void;
}) {
  // "default" is the program's own default, which the first entry already stands for
  const known = knownModels.filter((m) => m.value !== "default");
  const [typing, setTyping] = useState(known.length === 0);
  const [text, setText] = useState(model ?? "");
  const [note, setNote] = useState<string | null>(null);
  const typed = text.trim() || null;
  // a model saved by its name (a default model, say) is the listed model of that name, as the runner matches it
  const find = (m: string | null) =>
    m === null
      ? knownModels.find((k) => k.value === "default")
      : known.find((k) => k.value === m || [k.value, k.name].some((n) => modelKey(n) === modelKey(m)));
  const match = model === null ? undefined : find(model);
  const label = match?.name ?? model;

  const levelsOf = (m: string | null) => {
    const entry = find(m);
    // an unknown model (typed, or before the first run) may have any of the usual levels; the runner checks
    return entry ? entry.efforts.filter((e) => e.value !== "default") : COMMON_EFFORTS;
  };
  const sameEffort = (l: { value: string; name: string }, e: string) => modelKey(l.value) === modelKey(e) || modelKey(l.name) === modelKey(e);
  const levels = levelsOf(model);
  const effortMatch = effort === null ? undefined : levels.find((l) => sameEffort(l, effort));
  const effortLabel = effortMatch?.name ?? (effort && effortName(effort));

  const pickModel = (next: string | null) => {
    if (effort && !levelsOf(next).some((l) => sameEffort(l, effort))) {
      const name = next === null ? "The program's default model" : (find(next)?.name ?? next);
      setNote(`${name} has no ${effortLabel} effort, so Effort went back to Model default.`);
      return onSave({ model: next, effort: null });
    }
    setNote(null);
    return onSave({ model: next });
  };

  return (
    <div className="space-y-1">
      <div className="grid gap-3 sm:grid-cols-[2fr_1fr]">
        {typing ? (
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Input label="Model" value={text} onChange={(e) => setText(e.target.value)} placeholder="Program default" maxLength={100} />
            </div>
            <Button variant="ghost" aria-label="Save model" disabled={typed === model} onClick={() => pickModel(typed)}>
              Save
            </Button>
            {known.length > 0 && (
              <Button variant="ghost" onClick={() => setTyping(false)}>
                List
              </Button>
            )}
          </div>
        ) : (
          <Select
            label="Model"
            value={match?.value ?? model ?? ""}
            onChange={(e) => {
              if (e.target.value === OTHER) {
                setText("");
                setTyping(true);
              } else {
                void pickModel(e.target.value || null);
              }
            }}
          >
            <option value="">Program default</option>
            {/* a name typed earlier that the agent didn't list stays visible */}
            {model && !match && <option value={model}>{model}</option>}
            {known.map((m) => (
              <option key={m.value} value={m.value}>{m.name}</option>
            ))}
            <option value={OTHER}>Other…</option>
          </Select>
        )}
        {levels.length === 0 ? (
          <Select label="Effort" value="" disabled>
            <option value="">Not adjustable</option>
          </Select>
        ) : (
          <Select
            label="Effort"
            value={effortMatch?.value ?? effort ?? ""}
            onChange={(e) => {
              setNote(null);
              void onSave({ effort: e.target.value || null });
            }}
          >
            <option value="">Model default</option>
            {effort && !effortMatch && <option value={effort}>{effortName(effort)}</option>}
            {levels.map((l) => (
              <option key={l.value} value={l.value}>{l.name}</option>
            ))}
          </Select>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {model ? `Runs start on ${label}` : "Runs use the program's own default model"}
        {effortLabel ? ` with ${effortLabel} effort.` : "."}
      </p>
      {note && <p role="status" className="text-xs text-amber">{note}</p>}
      {knownModels.length === 0 && (
        <p className="text-xs text-muted-foreground">
          Type a model name or alias; the models it offers, and each one&apos;s effort levels, are listed here after its first run.
        </p>
      )}
    </div>
  );
}
