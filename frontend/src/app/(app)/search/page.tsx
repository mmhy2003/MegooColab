"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { SearchResults } from "@/components/search/SearchResults";
import { PageHeader } from "@/components/ui/PageHeader";
import { paramsFromUrl } from "@/lib/search";

function SearchPageBody() {
  const router = useRouter();
  const sp = useSearchParams();
  // the page shows a change at once; the URL follows, so the search can be shared or bookmarked
  const [params, setParams] = useState(() => paramsFromUrl(new URLSearchParams(sp.toString())));
  return (
    <SearchResults
      params={params}
      onChange={(p, url) => {
        setParams(p);
        router.replace(`/search?${url}`);
      }}
    />
  );
}

/** A new query (from the Ctrl+K box, say) starts the page over; filter changes keep it. */
function SearchPageKeyed() {
  const sp = useSearchParams();
  return <SearchPageBody key={sp.get("q") ?? ""} />;
}

export default function SearchPage() {
  return (
    <div className="space-y-4">
      <PageHeader title="Search" subtitle="Everything you can open: tasks, documents, projects, teams, people, agents and questions." />
      <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
        <SearchPageKeyed />
      </Suspense>
    </div>
  );
}
