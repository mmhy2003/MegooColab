"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { modelKey } from "@/lib/agents";
import type { ModelOption } from "@/lib/types";

const OTHER = "__other";

/** The model an agent's runs start on: one it offered on its last run, or any name typed (an alias such as "opus"). */
export function ModelField({
  model,
  knownModels,
  onSave,
}: {
  model: string | null;
  knownModels: ModelOption[];
  onSave: (model: string | null) => Promise<void> | void;
}) {
  // "default" is the program's own default, which the first entry already stands for
  const known = knownModels.filter((m) => m.value !== "default");
  const [typing, setTyping] = useState(known.length === 0);
  const [text, setText] = useState(model ?? "");
  const typed = text.trim() || null;
  // a model saved by its name (a default model, say) is the listed model of that name, as the runner matches it
  const match = model === null ? undefined : known.find((m) => m.value === model || [m.value, m.name].some((n) => modelKey(n) === modelKey(model)));
  const label = match?.name ?? model;
  return (
    <div className="space-y-1">
      {typing ? (
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <Input label="Model" value={text} onChange={(e) => setText(e.target.value)} placeholder="Program default" maxLength={100} />
          </div>
          <Button variant="ghost" aria-label="Save model" disabled={typed === model} onClick={() => onSave(typed)}>
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
              void onSave(e.target.value || null);
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
      <p className="text-xs text-muted-foreground">
        {model ? `Runs start on ${label}.` : "Runs use the program's own default model."}
      </p>
      {knownModels.length === 0 && (
        <p className="text-xs text-muted-foreground">
          Type a model name or alias; the models it offers are listed here after its first run.
        </p>
      )}
    </div>
  );
}
