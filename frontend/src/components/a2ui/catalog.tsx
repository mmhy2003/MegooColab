"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Input, Textarea } from "@/components/ui/Input";
import { Markdown } from "@/components/ui/Markdown";
import { TabPanel, Tabs as UiTabs } from "@/components/ui/Tabs";

/** MegooColab's A2UI catalog (backend/app/a2ui/catalog.json). */
export const CATALOG_ID = "urn:megoocolab:a2ui:catalog:v1";

/** A task key, as the backend's app.a2ui.service.TASK_KEY. */
export const TASK_KEY = /^[A-Z][A-Z0-9]{1,9}-[1-9][0-9]*$/;

/** Each catalog component's property names, as catalog.json lists them (without "id" and "component"). */
export const COMPONENT_PROPS: Record<string, readonly string[]> = {
  Column: ["children", "justify", "align", "weight"],
  Row: ["children", "justify", "align", "weight"],
  Card: ["child", "weight"],
  Divider: ["axis", "weight"],
  Text: ["text", "variant", "weight"],
  TextField: ["label", "value", "placeholder", "variant", "weight"],
  CheckBox: ["label", "value", "weight"],
  ChoicePicker: ["label", "variant", "options", "value", "displayStyle", "filterable", "weight"],
  Slider: ["label", "min", "max", "value", "steps", "weight"],
  DateTimeInput: ["value", "enableDate", "enableTime", "min", "max", "label", "weight"],
  Tabs: ["tabs", "weight"],
  List: ["children", "direction", "align", "weight"],
  StatTile: ["label", "value", "caption", "tone", "weight"],
  TaskLink: ["task", "label", "weight"],
};

/** What every input of the catalog takes. `Surface` adapts the renderer's resolved props to it. */
export type FieldProps<V> = {
  id: string;
  label?: string;
  value: V;
  onChange: (v: V) => void;
  readOnly: boolean;
  /** the first failing check's message */
  error?: string;
};

const LABEL = "text-xs tracking-wider text-muted-foreground uppercase";

/** A check message waits until the person has changed or left the field, and a read-only field shows none. */
function useMessage(readOnly: boolean, error: string | undefined) {
  const [touched, setTouched] = useState(false);
  return [touched && !readOnly ? error : undefined, () => setTouched(true)] as const;
}

function Message({ text }: { text?: string }) {
  return text ? <p className="text-xs text-pink">{text}</p> : null;
}

export function Column({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-2">{children}</div>;
}

export function Row({ children }: { children: ReactNode }) {
  return <div className="flex flex-row flex-wrap gap-2">{children}</div>;
}

export function Card({ children }: { children: ReactNode }) {
  return <div className="card px-3 py-2">{children}</div>;
}

export function Divider() {
  return <hr className="border-line" />;
}

export function Text({ text }: { text: string }) {
  return <Markdown compact>{text}</Markdown>;
}

/** Underline tabs with ui/Tabs' look and keys; the open tab is local state. Hidden panels stay mounted. */
export function Tabs({ id, tabs }: { id: string; tabs: { title: string; panel: ReactNode }[] }) {
  const [open, setOpen] = useState("0");
  const defs = tabs.map((t, i) => ({ id: `${id}-${i}`, label: t.title }));
  return (
    <div>
      <UiTabs label="Tabs" tabs={defs} value={`${id}-${open}`} onChange={(v) => setOpen(v.slice(id.length + 1))} />
      {tabs.map((t, i) => (
        <TabPanel key={i} id={`${id}-${i}`} active={String(i) === open}>
          {t.panel}
        </TabPanel>
      ))}
    </div>
  );
}

/** Rows with a line between them; past about 15 rem it scrolls inside the card. */
export function List({ items }: { items: ReactNode[] }) {
  return (
    <div role="list" className="max-h-60 divide-y divide-line overflow-y-auto">
      {items.map((item, i) => (
        <div key={i} role="listitem" className="py-1.5">
          {item}
        </div>
      ))}
    </div>
  );
}

const TONE = { neutral: "", good: "text-green-ink", warning: "text-amber", bad: "text-pink" } as const;

/** The Dashboard Tile's look: a mono value, its label, a caption. */
export function StatTile({
  label,
  value,
  caption,
  tone = "neutral",
}: {
  label: string;
  value: string;
  caption?: string;
  tone?: keyof typeof TONE;
}) {
  return (
    <div role="group" aria-label={label} data-tone={tone} className="card min-w-0 px-3 py-2.5">
      <p className={`font-mono text-2xl leading-tight font-semibold ${TONE[tone] ?? ""}`}>{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
      {caption && <p className="text-[11px] text-muted-foreground">{caption}</p>}
    </div>
  );
}

/** A task's key as a link to its board drawer, then the agent's label; anything else as plain text. */
export function TaskLink({ task, label }: { task: string; label?: string }) {
  if (!TASK_KEY.test(task)) return <span>{[task, label].filter(Boolean).join(" ")}</span>;
  return (
    <span>
      <Link
        href={`/projects/${task.replace(/-\d+$/, "")}/board?task=${task}`}
        className="font-mono text-cyan-ink underline"
      >
        {task}
      </Link>
      {label && ` ${label}`}
    </span>
  );
}

export function TextField({
  id,
  label,
  value,
  onChange,
  readOnly,
  error,
  variant = "shortText",
  placeholder,
}: FieldProps<string> & { variant?: "shortText" | "longText" | "number"; placeholder?: string }) {
  const [message, touch] = useMessage(readOnly, error);
  // like the A2UI renderers, every variant stores the text the field holds: a number field stores "3", and an
  // emptied field stores ""; the numeric check reads it with Number()
  const change = (v: string) => {
    touch();
    onChange(v);
  };
  if (variant === "longText") {
    return (
      <div className="flex flex-col gap-1">
        <Textarea
          id={id}
          label={label}
          value={value}
          placeholder={placeholder}
          disabled={readOnly}
          aria-invalid={message ? true : undefined}
          onChange={(e) => change(e.target.value)}
          onBlur={touch}
        />
        <Message text={message} />
      </div>
    );
  }
  return (
    <Input
      id={id}
      label={label}
      type={variant === "number" ? "number" : "text"}
      value={value}
      placeholder={placeholder}
      disabled={readOnly}
      error={message}
      onChange={(e) => change(e.target.value)}
      onBlur={touch}
    />
  );
}

export function CheckBox({ id, label, value, onChange, readOnly, error }: FieldProps<boolean>) {
  const [message, touch] = useMessage(readOnly, error);
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="flex items-center gap-2 text-sm text-fg">
        <input
          id={id}
          type="checkbox"
          className="accent-cyan"
          checked={value}
          disabled={readOnly}
          onChange={(e) => {
            touch();
            onChange(e.target.checked);
          }}
          onBlur={touch}
        />
        {label}
      </label>
      <Message text={message} />
    </div>
  );
}

export function ChoicePicker({
  id,
  label,
  value,
  onChange,
  readOnly,
  error,
  options,
  multiple,
  chips,
}: FieldProps<string[]> & { options: { label: string; value: string }[]; multiple: boolean; chips: boolean }) {
  const [message, touch] = useMessage(readOnly, error);
  // the A2UI renderers' rule: one choice replaces the selection, many toggle in and out of it
  const toggle = (v: string) => {
    touch();
    onChange(multiple ? (value.includes(v) ? value.filter((x) => x !== v) : [...value, v]) : [v]);
  };
  return (
    <fieldset className="flex flex-col gap-1" aria-label={label ? undefined : id}>
      {label && <legend className={`${LABEL} mb-1`}>{label}</legend>}
      <div className={chips ? "flex flex-wrap gap-2" : "flex flex-col gap-1"}>
        {options.map((o) =>
          chips ? (
            <button
              key={o.value}
              type="button"
              aria-pressed={value.includes(o.value)}
              disabled={readOnly}
              className="rounded-full border border-line px-3 py-1 text-xs text-fg aria-pressed:border-cyan aria-pressed:bg-surface-2 disabled:opacity-60"
              onClick={() => toggle(o.value)}
              onBlur={touch}
            >
              {o.label}
            </button>
          ) : (
            <label key={o.value} className="flex items-center gap-2 text-sm text-fg">
              <input
                type={multiple ? "checkbox" : "radio"}
                name={multiple ? undefined : id}
                value={o.value}
                className="accent-cyan"
                checked={value.includes(o.value)}
                disabled={readOnly}
                onChange={() => toggle(o.value)}
                onBlur={touch}
              />
              {o.label}
            </label>
          ),
        )}
      </div>
      <Message text={message} />
    </fieldset>
  );
}

export function Slider({
  id,
  label,
  value,
  onChange,
  readOnly,
  error,
  min = 0,
  max,
  steps,
}: FieldProps<number> & { min?: number; max: number; steps?: number }) {
  const [message, touch] = useMessage(readOnly, error);
  // `steps` divides the range into that many parts, as the A2UI renderers read it
  const step = steps && steps > 0 && max > min ? (max - min) / steps : undefined;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between gap-2">
        <label htmlFor={id} className={LABEL}>{label}</label>
        <output htmlFor={id} className="font-mono text-xs text-fg">{value}</output>
      </div>
      <input
        id={id}
        type="range"
        aria-label={label ? undefined : id}
        className="w-full accent-cyan"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={readOnly}
        onChange={(e) => {
          touch();
          onChange(Number(e.target.value));
        }}
        onBlur={touch}
      />
      <Message text={message} />
    </div>
  );
}

type DateTimeType = "date" | "time" | "datetime-local";

/** What an input of `type` accepts from an ISO 8601 value: no seconds and no time zone, or it shows empty. */
function forInput(value: string, type: DateTimeType) {
  const [date, time] = value.includes("T") ? value.split("T") : value.includes(":") ? ["", value] : [value, ""];
  if (type === "date") return date.slice(0, 10);
  if (type === "time") return time.slice(0, 5);
  return date && time ? `${date.slice(0, 10)}T${time.slice(0, 5)}` : "";
}

export function DateTimeInput({
  id,
  label,
  value,
  onChange,
  readOnly,
  error,
  enableDate,
  enableTime,
  min,
  max,
}: FieldProps<string> & { enableDate?: boolean; enableTime?: boolean; min?: string; max?: string }) {
  const [message, touch] = useMessage(readOnly, error);
  // with neither flag the A2UI renderers ask for a date
  const type: DateTimeType = enableTime ? (enableDate ? "datetime-local" : "time") : "date";
  return (
    <Input
      id={id}
      label={label}
      aria-label={label ? undefined : id}
      type={type}
      value={forInput(value, type)}
      min={min ? forInput(min, type) || undefined : undefined}
      max={max ? forInput(max, type) || undefined : undefined}
      disabled={readOnly}
      error={message}
      // the value the input holds: "2026-12-01", "09:30" or "2026-12-01T09:30"
      onChange={(e) => {
        touch();
        onChange(e.target.value);
      }}
      onBlur={touch}
    />
  );
}
