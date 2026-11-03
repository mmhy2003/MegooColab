"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { api, ApiError } from "@/lib/api";
import { gitTestError, type GitKind, type RepoChoices, useConnectionNames } from "@/lib/git";

export type PickedRepo = { connectionId: string; kind: GitKind; path: string; url: string; defaultBranch: string | null };

/** A project's next repository, picked from what a provider connection's token can see: choose the provider, then
 * search its repositories (the first page shows at once). Picking one fills in name, address and default branch. */
export function RepoPicker({ projectKey, onPick }: { projectKey: string; onPick: (r: PickedRepo) => void }) {
  const connections = useConnectionNames();
  const [connectionId, setConnectionId] = useState("");
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const wait = setTimeout(() => setQ(typed.trim()), 300);
    return () => clearTimeout(wait);
  }, [typed]);
  const choices = useInfiniteQuery({
    queryKey: ["git", "choices", projectKey, connectionId, q],
    enabled: Boolean(connectionId),
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      api<RepoChoices>(
        `/api/projects/${projectKey}/repositories/choices?${new URLSearchParams({ connection_id: connectionId, q, page: String(pageParam) })}`,
      ),
    getNextPageParam: (last, all) => (last.more ? all.length + 1 : undefined),
  });
  const kind = connections.data?.find((c) => c.id === connectionId)?.kind;
  const items = choices.data?.pages.flatMap((p) => p.items) ?? [];
  const failure = choices.error instanceof ApiError ? gitTestError(choices.error.detail) : choices.error ? gitTestError(null) : null;

  return (
    <div className="space-y-2">
      <Select label="Provider" value={connectionId} onChange={(e) => setConnectionId(e.target.value)}>
        <option value="">Choose a provider…</option>
        {(connections.data ?? []).map((c) => (
          <option key={c.id} value={c.id}>{c.name}</option>
        ))}
      </Select>
      {connectionId && (
        <>
          <label className="flex flex-col gap-1">
            <span className="text-xs tracking-wider text-muted-foreground uppercase">Repository</span>
            <input
              type="search"
              placeholder="Search…"
              className="rounded border border-line bg-surface-2 px-2 py-2 text-sm"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
          </label>
          {failure && <p role="alert" className="text-sm text-pink">{failure}</p>}
          {choices.isPending && !failure && <p className="text-xs text-muted-foreground">Loading…</p>}
          {items.length > 0 && (
            <ul aria-label="Repositories" className="max-h-64 divide-y divide-line overflow-y-auto rounded border border-line">
              {items.map((r) => (
                <li key={r.path}>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-2 py-2 text-left text-sm hover:bg-surface-2"
                    onClick={() => kind && onPick({ connectionId, kind, path: r.path, url: r.url, defaultBranch: r.default_branch })}
                  >
                    <span className="min-w-0 flex-1 truncate">{r.path}</span>
                    {r.default_branch && <span className="text-xs text-muted-foreground">{r.default_branch}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {choices.isSuccess && items.length === 0 && (
            <p className="text-xs text-muted-foreground">No repository matches. Not listed? Enter it by hand.</p>
          )}
          {choices.hasNextPage && (
            <Button variant="ghost" disabled={choices.isFetchingNextPage} onClick={() => void choices.fetchNextPage()}>
              Load more
            </Button>
          )}
        </>
      )}
    </div>
  );
}
