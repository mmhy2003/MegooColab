"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Dialog } from "@/components/ui/Dialog";
import { ApiError } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { KIND_LABELS, plain, useQuickSearch, type Hit, type SearchKind } from "@/lib/search";

import { Highlighted } from "./Highlighted";
import { ResultCard } from "./ResultCard";

export const UNAVAILABLE = "Search is unavailable right now";

export function searchError(err: unknown): string {
  return err instanceof ApiError && err.status === 503 ? UNAVAILABLE : errorMessage(err);
}

/** The quick search box (Ctrl+K): results grouped by kind as you type, arrow keys to move, Enter to open. Mounted
 * only while open, so each opening starts empty. */
export function SearchBox({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const [card, setCard] = useState<Hit | null>(null);
  const results = useQuickSearch(open ? q : "");
  const groups = q.trim() ? (results.data?.groups ?? []) : [];
  const flat = groups.flatMap((g) => g.hits);

  const choose = (hit: Hit) => {
    if (hit.url) {
      onClose();
      router.push(hit.url);
    } else {
      setCard(hit);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown" && flat.length) {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, flat.length - 1));
    } else if (e.key === "ArrowUp" && flat.length) {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && flat[active]) {
      e.preventDefault();
      choose(flat[active]);
    }
  };

  // each group's first option index, for keyboard selection across groups
  const starts = groups.map((_, gi) => groups.slice(0, gi).reduce((n, g) => n + g.hits.length, 0));
  return (
    <Dialog open={open} onClose={onClose} title="Search" wide dismissible>
      <div className="space-y-3">
        <input
          autoFocus
          role="combobox"
          aria-label="Search"
          aria-expanded={flat.length > 0}
          aria-controls="quick-search-results"
          placeholder="Search tasks, docs, people…"
          className="w-full rounded border border-line bg-surface-2 px-3 py-2 text-sm"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setActive(0);
            setCard(null);
          }}
          onKeyDown={onKeyDown}
        />
        {results.error && q.trim() && (
          <p role="alert" className="text-sm text-pink">
            {searchError(results.error)}
          </p>
        )}
        {card ? (
          <div className="space-y-3">
            <ResultCard hit={card} onNavigate={onClose} />
            <button type="button" className="text-xs text-cyan-ink underline" onClick={() => setCard(null)}>
              Back to results
            </button>
          </div>
        ) : (
          groups.length > 0 && (
            <div id="quick-search-results" role="listbox" aria-label="Results" className="max-h-[60vh] space-y-3 overflow-auto">
              {groups.map((g, gi) => (
                <div key={g.kind} role="presentation" className="space-y-1">
                  <h3 className="text-[11px] tracking-widest text-muted uppercase">{KIND_LABELS[g.kind as SearchKind] ?? g.kind}</h3>
                  {g.hits.map((hit, hi) => {
                    const mine = starts[gi] + hi;
                    return (
                      <div
                        key={`${hit.kind}-${hit.id}`}
                        role="option"
                        aria-selected={mine === active}
                        aria-label={`${plain(hit.key) ? `${plain(hit.key)} ` : ""}${plain(hit.title)}`}
                        tabIndex={-1}
                        onMouseEnter={() => setActive(mine)}
                        onClick={() => choose(hit)}
                        className={`cursor-pointer rounded px-2 py-1 text-sm ${mine === active ? "bg-surface-2" : ""}`}
                      >
                        {hit.key && (
                          <span className="mr-2 font-mono text-xs text-muted">
                            <Highlighted text={hit.key} />
                          </span>
                        )}
                        <Highlighted text={hit.title} />
                        {hit.snippet && (
                          <p className="truncate text-xs text-muted">
                            <Highlighted text={hit.snippet} />
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
              <Link
                href={`/search?${new URLSearchParams({ q: q.trim() })}`}
                onClick={onClose}
                className="block border-t border-line pt-2 text-right text-xs"
              >
                See all {results.data?.total ?? 0} results
              </Link>
            </div>
          )
        )}
      </div>
    </Dialog>
  );
}

/** The header's search button, plus the Ctrl+K / Cmd+K shortcut anywhere in the app. */
export function SearchLauncher() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <>
      <button type="button" className="icon-btn" aria-label="Search (Ctrl+K)" title="Search (Ctrl+K)" onClick={() => setOpen(true)}>
        <Search size={16} aria-hidden />
      </button>
      {open && <SearchBox open onClose={() => setOpen(false)} />}
    </>
  );
}
