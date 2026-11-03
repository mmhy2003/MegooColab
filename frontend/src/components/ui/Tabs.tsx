"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useRef } from "react";

import { ScrollX } from "@/components/ui/ScrollX";

export type TabDef<T extends string> = {
  id: T;
  label: string;
  /** a dot after the label: unsaved changes in this tab, unless markLabel says what else it means */
  mark?: boolean;
  markLabel?: string;
};

/** The open tab lives in the address (?tab=…), so a link or a reload lands on it. A missing or unknown tab opens the
 * first. Pages using this wrap their content in <Suspense> (useSearchParams). */
export function useTabParam<T extends string>(ids: readonly T[]): [T, (id: T) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const asked = params.get("tab");
  const current = ids.find((id) => id === asked) ?? ids[0];
  const choose = (id: T) => {
    const next = new URLSearchParams(params.toString());
    next.set("tab", id);
    router.replace(`${pathname}?${next}`, { scroll: false });
  };
  return [current, choose];
}

/** Underline tabs, as on a project's pages. Arrow keys, Home and End move between them; on a narrow screen the row
 * scrolls sideways instead of widening the page, its edge faded where more tabs hide. */
export function Tabs<T extends string>({
  label,
  tabs,
  value,
  onChange,
}: {
  label: string;
  tabs: readonly TabDef<T>[];
  value: T;
  onChange: (id: T) => void;
}) {
  const refs = useRef(new Map<T, HTMLButtonElement>());
  const go = (index: number) => {
    const tab = tabs[(index + tabs.length) % tabs.length];
    onChange(tab.id);
    refs.current.get(tab.id)?.focus();
  };
  const at = tabs.findIndex((t) => t.id === value);
  return (
    <ScrollX chevron className="mb-4 border-b border-line">
      <div role="tablist" aria-label={label} className="flex gap-1">
        {tabs.map((t) => {
          const selected = t.id === value;
          return (
            <button
              key={t.id}
              ref={(el) => {
                if (el) refs.current.set(t.id, el);
                else refs.current.delete(t.id);
              }}
              type="button"
              role="tab"
              id={`tab-${t.id}`}
              aria-controls={`panel-${t.id}`}
              aria-selected={selected}
              aria-label={t.mark ? `${t.label} (${t.markLabel ?? "unsaved changes"})` : undefined}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(t.id)}
              onKeyDown={(e) => {
                const move = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[e.key];
                if (move === undefined) return;
                e.preventDefault();
                go(move);
              }}
              className={`flex shrink-0 items-center gap-1.5 border-b-2 px-3 pb-2 text-sm whitespace-nowrap ${
                selected ? "border-cyan text-cyan-ink" : "border-transparent text-muted-foreground hover:text-fg"
              }`}
            >
              {t.label}
              {t.mark && <span aria-hidden className="size-1.5 rounded-full bg-amber" />}
            </button>
          );
        })}
      </div>
    </ScrollX>
  );
}

/** A tab's content. Hidden tabs stay mounted, so what was typed in them is kept. */
export function TabPanel({ id, active, children }: { id: string; active: boolean; children: React.ReactNode }) {
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} hidden={!active}>
      {children}
    </div>
  );
}
