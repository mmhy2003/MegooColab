"use client";

import { useQuery } from "@tanstack/react-query";

import { Markdown, wikiDocIds, type WikiTitles } from "@/components/ui/Markdown";
import { api } from "@/lib/api";
import { kbKeys } from "@/lib/kb";

/** Knowledge Base Markdown: wiki links resolved with one batched title lookup per body. */
export function KbMarkdown({ children }: { children: string }) {
  const ids = wikiDocIds(children).slice(0, 200);
  const titles = useQuery({
    queryKey: kbKeys.resolve(ids),
    queryFn: () => api<WikiTitles>("/api/kb/resolve", { method: "POST", json: { doc_ids: ids } }),
    enabled: ids.length > 0,
  });
  return <Markdown wiki={titles.data ?? {}}>{children}</Markdown>;
}
