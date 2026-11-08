"use client";

import { Check, ChevronsUpDown, X } from "lucide-react";
import { useState } from "react";

import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/shadcn/command";
import { Popover, PopoverAnchor, PopoverContent, PopoverTrigger } from "@/components/shadcn/popover";

type Project = { key: string; name: string };
export type ProjectCounts = Map<string, { active: number; total: number }>;

const TAGS = 2; // tags shown in the closed field; the rest are "+N more"

/** `text` with the first case-blind match of `query` marked. */
function Marked({ text, query }: { text: string; query: string }) {
  const at = query ? text.toLowerCase().indexOf(query.toLowerCase()) : -1;
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded-sm bg-amber/30 text-inherit">{text.slice(at, at + query.length)}</mark>
      {text.slice(at + query.length)}
    </>
  );
}

/**
 * Several projects picked from a searchable list (none picked: all of them). Closed, it shows the picked ones as tags,
 * each with its ✕; open, a search over keys and names, then a checkbox per project with its chats (active / all). The
 * ones picked when it opened come first, and stay there until it closes, so a row doesn't jump away as it's ticked.
 */
export function ProjectPicker({ projects, counts, value, onChange }: {
  projects: Project[];
  counts: ProjectCounts;
  value: string[];
  onChange: (keys: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  // the projects picked when it opened: they lead the list until it closes, so a row doesn't jump as it's ticked
  const [first, setFirst] = useState<string[]>([]);
  const picked = new Set(value);
  const byKey = new Map(projects.map((p) => [p.key, p]));
  const tags = value.filter((k) => byKey.has(k));

  const onOpenChange = (next: boolean) => {
    if (next) {
      setFirst(value);
      setQuery("");
    }
    setOpen(next);
  };
  const q = query.trim().toLowerCase();
  // ordered from the projects as they are now: a list that arrives after it opened still shows
  const lead = new Set(open ? first : []);
  const shown = [...projects.filter((p) => lead.has(p.key)), ...projects.filter((p) => !lead.has(p.key))].filter(
    (p) => !q || p.key.toLowerCase().includes(q) || p.name.toLowerCase().includes(q),
  );
  const toggle = (key: string) => onChange(picked.has(key) ? value.filter((k) => k !== key) : [...value, key]);
  const addAll = () => onChange([...value, ...shown.map((p) => p.key).filter((k) => !picked.has(k))]);

  return (
    <div className="space-y-1">
      <span className="text-xs tracking-wider text-muted-foreground uppercase">Projects</span>
      {/* the keyboard's focus ring goes round the whole field, not just the button inside it */}
      <Popover open={open} onOpenChange={onOpenChange}>
        <PopoverAnchor asChild>
          <div className="flex min-h-9 flex-wrap items-center gap-1 rounded border border-line bg-surface-2 py-1 pr-1 pl-1.5 focus-within:border-cyan has-[[role=combobox]:focus-visible]:outline-2 has-[[role=combobox]:focus-visible]:outline-offset-2 has-[[role=combobox]:focus-visible]:outline-cyan">
            {tags.slice(0, TAGS).map((k) => (
              <span key={k} className="inline-flex items-center gap-0.5 rounded border border-cyan/40 bg-cyan/10 pl-1.5 text-xs text-cyan-ink">
                {k}
                <button
                  type="button"
                  aria-label={`Remove ${k}`}
                  onClick={() => onChange(value.filter((v) => v !== k))}
                  className="inline-flex size-5 items-center justify-center text-muted-foreground hover:text-fg"
                >
                  <X size={12} aria-hidden />
                </button>
              </span>
            ))}
            <PopoverTrigger asChild>
              <button
                type="button"
                // eslint-disable-next-line jsx-a11y/role-has-required-aria-props -- PopoverTrigger adds aria-controls
                role="combobox"
                aria-label="Projects"
                aria-expanded={open}
                className="flex min-h-7 min-w-16 flex-1 items-center justify-between gap-2 px-1 text-left text-sm focus-visible:shadow-none! focus-visible:outline-none!"
              >
                <span className="min-w-0 truncate text-muted-foreground">
                  {tags.length === 0 ? <span className="text-fg">All projects</span> : tags.length > TAGS ? `+${tags.length - TAGS} more` : ""}
                </span>
                <ChevronsUpDown size={14} aria-hidden className="shrink-0 text-muted-foreground" />
              </button>
            </PopoverTrigger>
          </div>
        </PopoverAnchor>
        <PopoverContent align="start" collisionPadding={8} className="w-(--radix-popover-trigger-width) min-w-64 p-0">
          <Command shouldFilter={false}>
            {/* cmdk's own input: ↑ ↓ and Enter reach the list through it */}
            <CommandInput placeholder="Search projects…" value={query} onValueChange={setQuery} />
            <div className="flex items-center justify-between gap-2 border-b border-line px-2.5 py-1.5 text-xs text-muted-foreground">
              <span>
                {tags.length} of {projects.length} picked
              </span>
              <span className="flex gap-3">
                <button type="button" className="text-cyan-ink hover:underline" onClick={addAll}>
                  {q ? "Select shown" : "Select all"}
                </button>
                <button type="button" className="text-cyan-ink hover:underline" onClick={() => onChange([])}>
                  Clear
                </button>
              </span>
            </div>
            <CommandList>
              <CommandEmpty>{q ? `No project matches "${query.trim()}".` : "No projects."}</CommandEmpty>
              {shown.map((p) => {
                const on = picked.has(p.key);
                const c = counts.get(p.key) ?? { active: 0, total: 0 };
                return (
                  <CommandItem
                    key={p.key}
                    value={p.key}
                    data-key={p.key}
                    aria-checked={on}
                    aria-label={`${p.key} — ${p.name}, ${c.active} active of ${c.total} chats`}
                    onSelect={() => toggle(p.key)}
                    className="gap-2"
                  >
                    <span
                      aria-hidden
                      className={`inline-flex size-3.5 shrink-0 items-center justify-center rounded-sm border ${on ? "border-cyan bg-cyan text-on-accent" : "border-muted-foreground/60"}`}
                    >
                      {on && <Check size={10} strokeWidth={3} />}
                    </span>
                    <span className="min-w-8 rounded border border-line px-1 text-center text-[11px]">
                      <Marked text={p.key} query={q} />
                    </span>
                    <span className="min-w-0 flex-1 truncate">
                      <Marked text={p.name} query={q} />
                    </span>
                    <span className="shrink-0 text-[11px] text-muted-foreground" title={`${c.active} active of ${c.total} chats`}>
                      <span className={c.active ? "text-cyan-ink" : ""}>{c.active}</span> / {c.total}
                    </span>
                  </CommandItem>
                );
              })}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}

/**
 * One project picked from a searchable list, in the same look as ProjectPicker: closed, it shows the picked project's
 * key and name ("Choose a project" before one is picked); open, a search over keys and names and a row per project,
 * the picked one ticked. Picking one closes it. `disabled`: the project is fixed (a project's own Chats tab).
 */
export function ProjectSelect({ projects, value, onChange, disabled = false, label = "Project" }: {
  projects: Project[];
  value: string;
  onChange: (key: string) => void;
  disabled?: boolean;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const current = projects.find((p) => p.key === value);
  const q = query.trim().toLowerCase();
  const shown = projects.filter((p) => !q || p.key.toLowerCase().includes(q) || p.name.toLowerCase().includes(q));
  const onOpenChange = (next: boolean) => {
    if (next) setQuery("");
    setOpen(next);
  };

  return (
    <div data-project-select className="min-w-0 space-y-1">
      <span className="text-xs tracking-wider text-muted-foreground uppercase">{label}</span>
      <Popover open={open} onOpenChange={onOpenChange}>
        <PopoverTrigger asChild>
          <button
            type="button"
            // eslint-disable-next-line jsx-a11y/role-has-required-aria-props -- PopoverTrigger adds aria-controls
            role="combobox"
            aria-label={label}
            aria-expanded={open}
            disabled={disabled}
            className="flex min-h-9 w-full min-w-0 items-center gap-2 rounded border border-line bg-surface-2 px-2.5 py-1 text-left text-sm focus-visible:border-cyan disabled:opacity-60"
          >
            {value ? (
              <>
                <span className="min-w-8 shrink-0 rounded border border-line px-1 text-center text-[11px]">{value}</span>
                <span className="min-w-0 flex-1 truncate">{current?.name ?? ""}</span>
              </>
            ) : (
              <span className="min-w-0 flex-1 truncate text-muted-foreground">Choose a project</span>
            )}
            {!disabled && <ChevronsUpDown size={14} aria-hidden className="shrink-0 text-muted-foreground" />}
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" collisionPadding={8} className="w-(--radix-popover-trigger-width) min-w-64 p-0">
          <Command shouldFilter={false}>
            <CommandInput placeholder="Search projects…" value={query} onValueChange={setQuery} />
            <CommandList>
              <CommandEmpty>{q ? `No project matches "${query.trim()}".` : "No projects."}</CommandEmpty>
              {shown.map((p) => {
                const on = p.key === value;
                return (
                  <CommandItem
                    key={p.key}
                    value={p.key}
                    data-key={p.key}
                    aria-checked={on}
                    aria-label={`${p.key} — ${p.name}`}
                    onSelect={() => {
                      onChange(p.key);
                      setOpen(false);
                    }}
                    className="gap-2"
                  >
                    <Check size={14} aria-hidden className={`shrink-0 text-cyan-ink ${on ? "" : "invisible"}`} />
                    <span className="min-w-8 rounded border border-line px-1 text-center text-[11px]">
                      <Marked text={p.key} query={q} />
                    </span>
                    <span className="min-w-0 flex-1 truncate">
                      <Marked text={p.name} query={q} />
                    </span>
                  </CommandItem>
                );
              })}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
