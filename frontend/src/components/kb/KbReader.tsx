"use client";

import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { FolderTree } from "@/components/kb/FolderTree";
import { BackLink } from "@/components/nav/BackLink";
import { SideListLayout } from "@/components/nav/SideListLayout";
import { folderChain, useKbSpaces, useKbTree } from "@/lib/kb";
import { useTrail, type Crumb } from "@/lib/trail";

/** Searches the Knowledge Base, this space first (the results page can widen it to every space). */
export function KbSearchBox({ spaceId }: { spaceId: string }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  return (
    <form
      role="search"
      className="flex min-w-[12rem] flex-1 sm:max-w-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (q.trim()) router.push(`/kb/search?${new URLSearchParams({ q: q.trim(), space: spaceId })}`);
      }}
    >
      <label className="relative flex-1">
        <Search size={14} aria-hidden className="absolute top-1/2 left-2 -translate-y-1/2 text-muted-foreground" />
        <input
          type="search"
          aria-label="Search the Knowledge Base"
          placeholder="Search the Knowledge Base…"
          maxLength={500}
          className="w-full rounded border border-line bg-surface-2 py-1.5 pr-2 pl-7 text-sm text-fg placeholder:text-muted-foreground focus:border-cyan focus:outline-none"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </label>
    </form>
  );
}

/** A space's folder or document with the space's tree beside it, the trail down to it, Back and search. */
export function KbReader({
  spaceId,
  folderId,
  docId,
  docTitle,
  editing,
  children,
}: {
  spaceId: string;
  folderId: string | null;
  docId?: string;
  docTitle?: string;
  editing?: boolean;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const spaces = useKbSpaces();
  const tree = useKbTree(spaceId);
  const space = spaces.data?.find((s) => s.id === spaceId);
  const folders = tree.data?.folders ?? [];
  const documents = tree.data?.documents ?? [];
  const chain = folderChain(folders, folderId);
  const folderHref = (id: string | null) => (id ? `/kb/${spaceId}?folder=${id}` : `/kb/${spaceId}`);

  const crumbs: Crumb[] = [
    { label: "Knowledge Base", href: "/kb" },
    { label: space?.name ?? null, href: `/kb/${spaceId}` },
    ...(folderId && !tree.data ? [{ label: null }] : chain.map((f) => ({ label: f.name, href: folderHref(f.id) }))),
    ...(docTitle !== undefined ? [{ label: docTitle }] : []),
  ];
  useTrail(crumbs);

  // one level up: a document's folder, a folder's parent, the space's top level the Knowledge Base
  const spaceName = space?.name ?? "the space";
  const up = docId
    ? folderId
      ? { href: folderHref(folderId), label: chain[chain.length - 1]?.name ?? "the folder" }
      : { href: folderHref(null), label: spaceName }
    : folderId
      ? chain.length > 1
        ? { href: folderHref(chain[chain.length - 2].id), label: chain[chain.length - 2].name }
        : { href: folderHref(null), label: spaceName }
      : { href: "/kb", label: "Knowledge Base" };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <BackLink area="kb-read" fallback={up} />
        <KbSearchBox spaceId={spaceId} />
      </div>
      <SideListLayout
        sideLabel="Files"
        hideSide={editing}
        side={
          <FolderTree
            spaceId={spaceId}
            folders={folders}
            documents={documents}
            selected={docId ? null : folderId}
            currentDocId={docId ?? null}
            onSelect={(id) => router.push(folderHref(id))}
            canWrite={Boolean(space?.can_write)}
          />
        }
      >
        {children}
      </SideListLayout>
    </div>
  );
}
