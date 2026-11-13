"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import {
  STAGE_ROWS,
  cleanStages,
  effortLevels,
  effortName,
  findModel,
  sameEffort,
  type StageKey,
  type StageModels,
} from "@/lib/agents";
import type { ModelOption } from "@/lib/types";

const OTHER = "__other";

/** A model and effort for each workflow stage (Design, Plan, Build, Review, Finish). A stage left "As above" runs on
 * the agent's own Model and Effort; a stage with its own model runs on that model's default effort unless it picks
 * one. Each change saves at once; a run that's going keeps what it started on. */
export function StageModelsField({
  agentModel,
  agentEffort,
  knownModels,
  value,
  onSave,
  notice = null,
}: {
  agentModel: string | null;
  agentEffort: string | null;
  knownModels: ModelOption[];
  value: StageModels;
  onSave: (rows: StageModels) => Promise<void> | void;
  /** a note from outside: a stage reset when the agent's own model changed */
  notice?: string | null;
}) {
  const [note, setNote] = useState<string | null>(null);
  const [typing, setTyping] = useState<StageKey | null>(null);
  const [text, setText] = useState("");
  const known = knownModels.filter((m) => m.value !== "default");
  const modelName = (m: string | null) => findModel(knownModels, m)?.name ?? m ?? "Program default";
  const agentLabel = agentModel ? modelName(agentModel) : "Program default";
  const agentEffortLabel = (() => {
    if (!agentEffort) return "Model default";
    const l = effortLevels(knownModels, agentModel).find((x) => sameEffort(x, agentEffort));
    return l?.name ?? effortName(agentEffort);
  })();

  const save = (key: StageKey, row: { model?: string | null; effort?: string | null }) =>
    onSave(cleanStages({ ...value, [key]: row }));

  const pickModel = (key: StageKey, label: string, next: string | null) => {
    const row = value[key] ?? {};
    const effort = row.effort ?? null;
    if (effort && !effortLevels(knownModels, next ?? agentModel).some((l) => sameEffort(l, effort))) {
      const effortLabel = effortLevels(knownModels, row.model ?? agentModel).find((l) => sameEffort(l, effort))?.name ?? effortName(effort);
      setNote(
        `${next ? modelName(next) : agentLabel} has no ${effortLabel} effort, so ${label}'s effort went back to ${next ? "Model default" : "As above"}.`,
      );
      return save(key, { model: next });
    }
    setNote(null);
    return save(key, { model: next, effort });
  };

  return (
    <div className="space-y-2">
      <h3 className="text-xs tracking-wider text-muted-foreground uppercase">Model by stage</h3>
      <div className="space-y-2">
        {STAGE_ROWS.map(({ key, label, note: rowNote }) => {
          const row = value[key] ?? {};
          const own = !!(row.model || row.effort);
          const mark = own ? "border-violet" : "";
          const match = row.model ? findModel(knownModels, row.model) : undefined;
          const levels = effortLevels(knownModels, row.model ?? agentModel);
          const effortMatch = row.effort ? levels.find((l) => sameEffort(l, row.effort!)) : undefined;
          return (
            <div key={key} className="grid items-center gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1fr)]">
              <div className="text-sm">
                {label}
                {rowNote && <span className="block text-xs text-muted-foreground">{rowNote}</span>}
              </div>
              {typing === key ? (
                <div className="flex items-center gap-2">
                  <div className="flex-1">
                    <Input aria-label={`${label} model`} value={text} onChange={(e) => setText(e.target.value)} maxLength={100} />
                  </div>
                  <Button variant="ghost" disabled={!text.trim()} onClick={() => { setTyping(null); void pickModel(key, label, text.trim()); }}>
                    Save
                  </Button>
                  <Button variant="ghost" onClick={() => setTyping(null)}>
                    Cancel
                  </Button>
                </div>
              ) : (
                <Select
                  aria-label={`${label} model`}
                  className={mark}
                  value={match?.value ?? row.model ?? ""}
                  onChange={(e) => {
                    if (e.target.value === OTHER) {
                      setText("");
                      setTyping(key);
                    } else {
                      void pickModel(key, label, e.target.value || null);
                    }
                  }}
                >
                  <option value="">As above ({agentLabel})</option>
                  {/* a name typed earlier that the agent didn't list stays visible */}
                  {row.model && !match && <option value={row.model}>{row.model}</option>}
                  {known.map((m) => (
                    <option key={m.value} value={m.value}>{m.name}</option>
                  ))}
                  <option value={OTHER}>Other…</option>
                </Select>
              )}
              {levels.length === 0 ? (
                <Select aria-label={`${label} effort`} className={mark} value="" disabled>
                  <option value="">Not adjustable</option>
                </Select>
              ) : (
                <Select
                  aria-label={`${label} effort`}
                  className={mark}
                  value={effortMatch?.value ?? row.effort ?? ""}
                  onChange={(e) => {
                    setNote(null);
                    void save(key, { model: row.model ?? null, effort: e.target.value || null });
                  }}
                >
                  <option value="">{row.model ? "Model default" : `As above (${agentEffortLabel})`}</option>
                  {row.effort && !effortMatch && <option value={row.effort}>{effortName(row.effort)}</option>}
                  {levels.map((l) => (
                    <option key={l.value} value={l.value}>{l.name}</option>
                  ))}
                </Select>
              )}
            </div>
          );
        })}
      </div>
      {(note ?? notice) && <p role="status" className="text-xs text-amber">{note ?? notice}</p>}
      <p className="text-xs text-muted-foreground">
        Chats and scheduled jobs use the agent&apos;s own model. A run that&apos;s already going keeps the model it started on.
      </p>
    </div>
  );
}
