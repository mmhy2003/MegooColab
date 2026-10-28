"use client";

import { FilePlus } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { DocList } from "@/components/kb/DocList";
import { FolderTree } from "@/components/kb/FolderTree";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useKbSpaces, useKbTree, type KbDocument } from "@/lib/kb";

export default function KbSpacePage() {
  const { spaceId } = useParams<{ spaceId: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const folder = search.get("folder");
  const spaces = useKbSpaces();
  const tree = useKbTree(spaceId);
  const space = spaces.data?.find((s) => s.id === spaceId);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (tree.isError) {
    return (
      <div className="card mx-auto mt-10 max-w-md p-6 text-center">
        <p className="text-pink">{errorMessage(tree.error)}</p>
        <Link href="/kb">Back to the Knowledge Base</Link>
      </div>
    );
  }
  const select = (id: string | null) => router.replace(id ? `/kb/${spaceId}?folder=${id}` : `/kb/${spaceId}`);
  const folderName = tree.data?.folders.find((f) => f.id === folder)?.name;

  return (
    <div>
      <PageHeader
        title={space?.name ?? "Knowledge Base"}
        subtitle={space ? `${space.kind === "org" ? "Organization" : space.kind === "team" ? "Team" : "Project"} space` : undefined}
        actions={
          space?.can_write && (
            <Button onClick={() => setCreating(true)}>
              <FilePlus size={14} aria-hidden /> New document
            </Button>
          )
        }
      />
      <p className="mb-4 text-sm">
        <Link href="/kb">Knowledge Base</Link>
      </p>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-[16rem_minmax(0,1fr)]">
        <aside className="card p-3">
          {tree.data && (
            <FolderTree
              spaceId={spaceId}
              folders={tree.data.folders}
              documents={tree.data.documents}
              selected={folder}
              onSelect={select}
              canWrite={Boolean(space?.can_write)}
            />
          )}
        </aside>
        <section className="card min-w-0 p-4">
          <h2 className="mb-2 text-xs tracking-widest text-muted uppercase">{folderName ?? "Top level"}</h2>
          {creating && (
            <form
              className="mb-4 space-y-2 rounded border border-line p-3"
              onSubmit={async (e) => {
                e.preventDefault();
                setError(null);
                try {
                  const doc = await api<KbDocument>(`/api/kb/spaces/${spaceId}/documents`, {
                    method: "POST",
                    json: { title: title.trim(), body_md: "", folder_id: folder },
                  });
                  router.push(`/kb/doc/${doc.id}?edit=1`);
                } catch (err) {
                  setError(errorMessage(err));
                }
              }}
            >
              <Input label="Title" required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
              {error && (
                <p role="alert" className="text-sm text-pink">
                  {error}
                </p>
              )}
              <div className="flex gap-2">
                <Button type="submit">Create</Button>
                <Button variant="ghost" onClick={() => setCreating(false)}>
                  Cancel
                </Button>
              </div>
            </form>
          )}
          {tree.data && <DocList documents={tree.data.documents} folderId={folder} />}
        </section>
      </div>
    </div>
  );
}
