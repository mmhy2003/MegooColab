"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

/** The item chosen in a list lives in the address (?agent=… or ?machine=…), next to the open tab. Choosing one is a
 * new history entry, so a phone's Back returns from its details to the list; clearing it replaces the entry. */
export function useChosenParam(key: "agent" | "machine"): [string | null, (id: string | null) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const choose = (id: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (id === null) next.delete(key);
    else next.set(key, id);
    const query = next.toString();
    const url = query ? `${pathname}?${query}` : pathname;
    if (id === null) router.replace(url, { scroll: false });
    else router.push(url, { scroll: false });
  };
  return [params.get(key), choose];
}

/** What a list shows beside it: the chosen item, else the first. Only a matching id counts as chosen, which is what
 * opens the details on a phone; a stale or unknown one leaves the list there. */
export function pickChosen<T>(items: T[], id: string | null, idOf: (t: T) => string): { shown: T | null; chosen: boolean } {
  const match = id === null ? undefined : items.find((t) => idOf(t) === id);
  return { shown: match ?? items[0] ?? null, chosen: match !== undefined };
}

/** A short list with the chosen item's details beside it. Below md, either the list or the details fill the screen,
 * the details under a Back button. */
export function ListDetail({
  listLabel,
  backLabel,
  chosen,
  onBack,
  list,
  detail,
}: {
  listLabel: string;
  backLabel: string;
  chosen: boolean;
  onBack: () => void;
  list: React.ReactNode;
  detail: React.ReactNode;
}) {
  return (
    <div className="grid min-w-0 gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] md:items-start">
      <nav aria-label={listLabel} className={`min-w-0 ${chosen ? "max-md:hidden" : ""}`}>
        {list}
      </nav>
      <div className={`min-w-0 space-y-3 ${chosen ? "" : "max-md:hidden"}`}>
        {chosen && (
          <button type="button" onClick={onBack} className="text-sm text-muted-foreground hover:text-fg md:hidden">
            ‹ {backLabel}
          </button>
        )}
        {detail}
      </div>
    </div>
  );
}

/** One row of a ListDetail list: a full-width button, its title on one line and a muted line under it. */
export function ListRow({
  selected,
  onClick,
  title,
  meta,
  aside,
}: {
  selected: boolean;
  onClick: () => void;
  title: React.ReactNode;
  meta?: React.ReactNode;
  aside?: React.ReactNode;
}) {
  return (
    <li className="flex min-w-0 items-center gap-2">
      <button
        type="button"
        onClick={onClick}
        aria-current={selected ? "true" : undefined}
        className={`flex min-w-0 flex-1 flex-col items-stretch rounded-lg border px-3 py-2 text-left ${
          selected ? "border-cyan bg-cyan/10" : "border-line hover:border-cyan/50"
        }`}
      >
        <span className="flex min-w-0 items-center gap-2 text-sm font-bold">{title}</span>
        {meta && <span className="truncate text-xs text-muted-foreground">{meta}</span>}
      </button>
      {aside}
    </li>
  );
}
