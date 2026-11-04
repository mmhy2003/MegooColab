"use client";

import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { useKbSearch, useKbTree, type KbSpaceRef } from "@/lib/kb";
import { kbDraftKeys, useDraftAgents, type KbDraft } from "@/lib/kbDrafts";

const TASK_KEY = /^[A-Za-z][A-Za-z0-9]*-\d+$/;

type Source = { kind: "task"; key: string } | { kind: "doc"; id: string; title: string };

/** Write with an agent: the agent, what the document should be (or what to change), what it should read first and,
 * for a new document, where it is saved. */
export function StartDraftDialog({
  open,
  onClose,
  space,
  folderId,
  document,
}: {
  open: boolean;
  onClose: () => void;
  space: KbSpaceRef;
  folderId: string | null;
  document?: { id: string; title: string };
}) {
  const router = useRouter();
  const client = useQueryClient();
  const agents = useDraftAgents(space.id, open);
  const tree = useKbTree(space.id);
  const [agent, setAgent] = useState("");
  const [brief, setBrief] = useState("");
  const [folder, setFolder] = useState(folderId ?? "");
  const [read, setRead] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const found = useKbSearch(TASK_KEY.test(read.trim()) ? "" : read.trim(), "");
  const list = agents.data ?? [];
  const usable = list.filter((a) => a.runner_ok);
  const chosen = agent || usable[0]?.id || "";

  const addTask = () => {
    const key = read.trim().toUpperCase();
    if (TASK_KEY.test(key) && !sources.some((s) => s.kind === "task" && s.key === key)) {
      setSources([...sources, { kind: "task", key }]);
    }
    setRead("");
  };
  const addDoc = (id: string, title: string) => {
    if (!sources.some((s) => s.kind === "doc" && s.id === id)) setSources([...sources, { kind: "doc", id, title }]);
    setRead("");
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const draft = await api<KbDraft>("/api/kb/drafts", {
        method: "POST",
        json: {
          space_id: space.id,
          folder_id: document ? null : folder || null,
          document_id: document?.id ?? null,
          agent_id: chosen,
          brief: brief.trim(),
          sources: sources.map((s) => (s.kind === "task" ? { kind: "task", key: s.key } : { kind: "doc", id: s.id })),
        },
      });
      await client.invalidateQueries({ queryKey: kbDraftKeys.all });
      onClose();
      router.push(`/kb/drafts/${draft.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const briefLabel = document ? "What should the agent change?" : "What should this document be?";
  return (
    <Dialog open={open} onClose={onClose} title={document ? `Write "${document.title}" with an agent` : "Write with an agent"}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {agents.isSuccess && list.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {space.kind === "project" ? "No agent can work on this project" : "You have no agents"}
          </p>
        ) : (
          <Select label="Agent" value={chosen} onChange={(e) => setAgent(e.target.value)}>
            {list.map((a) => (
              <option key={a.id} value={a.id} disabled={!a.runner_ok}>
                {a.name}
                {!a.runner_ok ? " (runner needs updating)" : !a.online ? " (offline)" : ""}
              </option>
            ))}
          </Select>
        )}
        <div className="flex flex-col gap-1">
          <label htmlFor="draft-brief" className="text-xs tracking-wider text-muted-foreground uppercase">
            {briefLabel}
          </label>
          <textarea
            id="draft-brief"
            value={brief}
            maxLength={20000}
            onChange={(e) => setBrief(e.target.value)}
            placeholder={
              document
                ? "For example: add a rollback section and shorten the prerequisites."
                : "For example: a runbook for deploying the payments service, for on-call engineers."
            }
            className="block min-h-28 w-full rounded border border-line bg-surface-2 p-2 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="draft-read" className="text-xs tracking-wider text-muted-foreground uppercase">
            Let it read
          </label>
          <div className="flex min-w-0 gap-2">
            <input
              id="draft-read"
              value={read}
              onChange={(e) => setRead(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addTask();
                }
              }}
              placeholder="A task key (PAY-12) or a document's title"
              className="min-w-0 flex-1 rounded border border-line bg-surface-2 px-2 py-1 text-sm"
            />
            <Button variant="ghost" onClick={addTask} disabled={!TASK_KEY.test(read.trim())}>
              Add task
            </Button>
          </div>
          {(found.data?.results ?? []).length > 0 && (
            <ul className="rounded border border-line text-sm">
              {found.data!.results.slice(0, 5).map((hit) => (
                <li key={hit.document_id}>
                  <button
                    type="button"
                    className="w-full truncate px-2 py-1 text-left hover:bg-surface-2"
                    onClick={() => addDoc(hit.document_id, hit.title)}
                  >
                    {hit.title} <span className="text-xs text-muted-foreground">{hit.space.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {sources.length > 0 && (
            <ul className="flex flex-wrap gap-1">
              {sources.map((s, i) => (
                <li key={s.kind === "task" ? s.key : s.id}
                  className="flex min-w-0 items-center gap-1 rounded-full border border-cyan px-2 text-xs text-cyan-ink">
                  <span className="truncate">{s.kind === "task" ? s.key : s.title}</span>
                  <button type="button" aria-label="Remove" onClick={() => setSources(sources.filter((_, j) => j !== i))}>
                    <X size={12} aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {!document && (
          <Select label="Save into" value={folder} onChange={(e) => setFolder(e.target.value)}>
            <option value="">{space.name} (top level)</option>
            {(tree.data?.folders ?? []).map((f) => (
              <option key={f.id} value={f.id}>
                {space.name} › {f.name}
              </option>
            ))}
          </Select>
        )}
        {error && (
          <p role="alert" className="text-sm text-pink">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy || !chosen || !brief.trim()}>
            Start drafting
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
