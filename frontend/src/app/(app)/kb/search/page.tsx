"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { SearchResults } from "@/components/kb/SearchResults";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { errorMessage } from "@/lib/errors";
import { useKbSearch, useKbSpaces } from "@/lib/kb";

export default function KbSearchPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
      <KbSearch />
    </Suspense>
  );
}

function KbSearch() {
  const router = useRouter();
  const params = useSearchParams();
  const q = params.get("q") ?? "";
  const space = params.get("space") ?? "";
  const [draft, setDraft] = useState(q);
  const [draftSpace, setDraftSpace] = useState(space);
  const spaces = useKbSpaces();
  const results = useKbSearch(q, space);

  return (
    <div className="max-w-3xl">
      <PageHeader title="Search the Knowledge Base" />
      <p className="mb-4 text-sm">
        <Link href="/kb">Knowledge Base</Link>
      </p>
      <form
        role="search"
        className="mb-4 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const next = new URLSearchParams();
          if (draft.trim()) next.set("q", draft.trim());
          if (draftSpace) next.set("space", draftSpace);
          router.push(`/kb/search?${next}`);
        }}
      >
        <input
          aria-label="Search"
          className="min-w-[12rem] flex-1 rounded border border-line bg-surface-2 px-3 py-2 text-sm text-fg focus:border-cyan focus:outline-none"
          maxLength={500}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <select
          aria-label="Space"
          className="rounded border border-line bg-surface-2 px-2 py-2 text-sm text-fg"
          value={draftSpace}
          onChange={(e) => setDraftSpace(e.target.value)}
        >
          <option value="">All spaces</option>
          {(spaces.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <Button type="submit">
          <Search size={14} aria-hidden /> Search
        </Button>
      </form>
      {results.error && <p className="text-sm text-pink">{errorMessage(results.error)}</p>}
      {results.isFetching && !results.data && <p className="text-sm text-muted">Searching…</p>}
      {results.data && <SearchResults query={q} results={results.data} />}
    </div>
  );
}
