"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { SearchResults } from "@/components/search/SearchResults";
import { PageHeader } from "@/components/ui/PageHeader";
import { paramsFromUrl } from "@/lib/search";

function SearchPageBody() {
  const router = useRouter();
  const sp = useSearchParams();
  const params = paramsFromUrl(new URLSearchParams(sp.toString()));
  return <SearchResults key={params.q} params={params} onChange={(_p, url) => router.replace(`/search?${url}`)} />;
}

export default function SearchPage() {
  return (
    <div className="space-y-4">
      <PageHeader title="Search" subtitle="Everything you can open: tasks, documents, projects, teams, people, agents and questions." />
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <SearchPageBody />
      </Suspense>
    </div>
  );
}
