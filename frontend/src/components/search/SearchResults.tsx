"use client";

import Link from "next/link";
import { useState } from "react";

import { api } from "@/lib/api";
import {
  KIND_LABELS,
  PAGE,
  STATUS_LABELS,
  UPDATED_LABELS,
  paramsToUrl,
  useSearch,
  type Hit,
  type SearchKind,
  type SearchParams,
  type SearchResults as Results,
} from "@/lib/search";

import { Highlighted } from "./Highlighted";
import { ResultCard } from "./ResultCard";
import { searchError } from "./SearchBox";

const FIELD = "rounded border border-line bg-surface-2 px-2 py-1 text-sm";
const TASK_ONLY = ["status", "assignee", "type", "label"] as const;

type ListName = "kind" | "project" | "status" | "assignee" | "type" | "label";

function FilterGroup({
  title,
  options,
  selected,
  onToggle,
}: {
  title: string;
  options: { value: string; label: string; count: number }[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  // a chosen value stays listed even when the current results hold none of it
  const shown = [...options];
  for (const v of selected) if (!shown.some((o) => o.value === v)) shown.push({ value: v, label: v, count: 0 });
  if (shown.length === 0) return null;
  return (
    <fieldset className="space-y-1">
      <legend className="text-[11px] tracking-widest text-muted uppercase">{title}</legend>
      {shown.map((o) => (
        <label key={o.value} className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={selected.includes(o.value)} onChange={() => onToggle(o.value)} />
          {`${o.label} (${o.count})`}
        </label>
      ))}
    </fieldset>
  );
}

function ResultItem({ hit }: { hit: Hit }) {
  const [open, setOpen] = useState(false);
  const label = KIND_LABELS[hit.kind as SearchKind] ?? hit.kind;
  return (
    <article className="space-y-0.5 border-b border-line py-2 text-sm">
      <p className="text-xs text-muted">
        {label}
        {hit.project_key && hit.kind !== "project" ? ` · ${hit.project_key}` : ""}
        {hit.status && hit.kind === "task" ? ` · ${STATUS_LABELS[hit.status] ?? hit.status}` : ""}
      </p>
      {hit.url ? (
        <Link href={hit.url} className="font-semibold">
          {hit.key && (
            <>
              <span className="font-mono text-xs">
                <Highlighted text={hit.key} />
              </span>{" "}
            </>
          )}
          <Highlighted text={hit.title} />
        </Link>
      ) : (
        <button type="button" className="font-semibold text-cyan-ink" onClick={() => setOpen((v) => !v)}>
          <Highlighted text={hit.title} />
        </button>
      )}
      {hit.snippet && (
        <p className="text-xs text-muted">
          <Highlighted text={hit.snippet} />
        </p>
      )}
      {open && <ResultCard hit={hit} />}
    </article>
  );
}

/** The hits of one search, with "Load more" appending the next pages. Keyed by the search, so it starts over. */
function HitList({ params, first }: { params: SearchParams; first: Results }) {
  const [more, setMore] = useState<Hit[]>([]);
  const [busy, setBusy] = useState(false);
  const hits = [...first.hits, ...more];
  return (
    <div>
      {hits.map((h) => (
        <ResultItem key={`${h.kind}-${h.id}`} hit={h} />
      ))}
      {hits.length < first.total && first.hits.length === PAGE && (
        <button
          type="button"
          disabled={busy}
          className="mt-3 text-xs text-cyan-ink underline"
          onClick={async () => {
            setBusy(true);
            try {
              const next = await api<Results>(`/api/search?${paramsToUrl({ ...params, offset: hits.length })}`);
              setMore((m) => [...m, ...next.hits]);
            } finally {
              setBusy(false);
            }
          }}
        >
          Load more
        </button>
      )}
    </div>
  );
}

/** The full results page (option B): query on top, filters on the left, results on the right. */
export function SearchResults({ params, onChange }: { params: SearchParams; onChange: (p: SearchParams, url: string) => void }) {
  const [draft, setDraft] = useState(params.q);
  const results = useSearch(params);
  const data = results.data;
  const facets = data?.facets;

  const change = (patch: Partial<SearchParams>) => {
    const next = { ...params, ...patch, offset: 0 };
    onChange(next, paramsToUrl(next));
  };
  const toggle = (name: ListName, value: string) => {
    const list = params[name];
    change({ [name]: list.includes(value) ? list.filter((v) => v !== value) : [...list, value] } as Partial<SearchParams>);
  };
  const taskOnly = TASK_ONLY.filter((n) => params[n].length > 0);

  return (
    <div className="space-y-4">
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          if (draft.trim()) change({ q: draft.trim() });
        }}
      >
        <input aria-label="Search" className={`${FIELD} w-full`} value={draft} onChange={(e) => setDraft(e.target.value)} />
      </form>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 md:grid-cols-[14rem_minmax(0,1fr)]">
        <aside aria-label="Filters" className="space-y-4">
          <FilterGroup
            title="Kind"
            options={Object.entries(facets?.kind ?? {}).map(([k, n]) => ({ value: k, label: KIND_LABELS[k as SearchKind] ?? k, count: n }))}
            selected={params.kind}
            onToggle={(v) => toggle("kind", v)}
          />
          <FilterGroup
            title="Project"
            options={(facets?.project ?? []).map((p) => ({ value: p.id, label: p.key, count: p.count }))}
            selected={params.project}
            onToggle={(v) => toggle("project", v)}
          />
          <FilterGroup
            title="Status"
            options={Object.keys(STATUS_LABELS)
              .filter((s) => facets?.status?.[s])
              .map((s) => ({ value: s, label: STATUS_LABELS[s], count: facets!.status[s] }))}
            selected={params.status}
            onToggle={(v) => toggle("status", v)}
          />
          <FilterGroup
            title="Assignee"
            options={(facets?.assignee ?? []).map((a) => ({ value: a.id, label: a.name, count: a.count }))}
            selected={params.assignee}
            onToggle={(v) => toggle("assignee", v)}
          />
          <FilterGroup
            title="Type"
            options={Object.entries(facets?.type ?? {}).map(([t, n]) => ({ value: t, label: t, count: n }))}
            selected={params.type}
            onToggle={(v) => toggle("type", v)}
          />
          <FilterGroup
            title="Labels"
            options={Object.entries(facets?.label ?? {}).map(([l, n]) => ({ value: l, label: l, count: n }))}
            selected={params.label}
            onToggle={(v) => toggle("label", v)}
          />
          <label className="block space-y-1 text-xs text-muted">
            Updated
            <select aria-label="Updated" className={`${FIELD} w-full`} value={params.updated ?? ""} onChange={(e) => change({ updated: e.target.value || null })}>
              <option value="">Any time</option>
              {Object.entries(UPDATED_LABELS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </label>
          {data?.meaning_available && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={params.meaning} onChange={() => change({ meaning: !params.meaning })} />
              Also match by meaning
            </label>
          )}
        </aside>
        <main className="min-w-0 space-y-3">
          <div className="flex items-center justify-between gap-2 text-xs text-muted">
            <span>{data ? `${data.total} results` : ""}</span>
            <label className="flex items-center gap-1">
              Sort
              <select aria-label="Sort" className={FIELD} value={params.sort} onChange={(e) => change({ sort: e.target.value as SearchParams["sort"] })}>
                <option value="relevance">Relevance</option>
                <option value="newest">Newest first</option>
              </select>
            </label>
          </div>
          {taskOnly.length > 0 && (
            <p className="text-xs text-muted">
              Showing tasks only ({taskOnly.join(" and ")} {taskOnly.length === 1 ? "applies" : "apply"} to tasks)
            </p>
          )}
          {results.error && (
            <p role="alert" className="text-sm text-pink">
              {searchError(results.error)}
            </p>
          )}
          {data?.meaning && data.meaning.length > 0 && (
            <section aria-label="Similar in meaning" className="card space-y-1 p-3">
              <h2 className="text-[11px] tracking-widest text-muted uppercase">Similar in meaning</h2>
              {data.meaning.map((h) => (
                <ResultItem key={`m-${h.id}`} hit={h} />
              ))}
            </section>
          )}
          {data && <HitList key={paramsToUrl(params)} params={params} first={data} />}
          {data && data.total === 0 && !data.meaning?.length && <p className="text-sm text-muted">Nothing matches.</p>}
        </main>
      </div>
    </div>
  );
}
