"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { DraftConversation } from "@/components/kb/drafts/DraftConversation";
import { DraftView } from "@/components/kb/drafts/DraftView";
import { MarkdownField } from "@/components/kb/MarkdownField";
import { NotFoundView } from "@/components/shell/NotFound";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Tabs } from "@/components/ui/Tabs";
import { ApiError, api } from "@/lib/api";
import { errorMessage, isNotFound } from "@/lib/errors";
import { draftTitle, kbDraftKeys, useKbDraft, type DraftTarget, type KbDraft } from "@/lib/kbDrafts";
import { usePageTitle } from "@/lib/title";
import { useUnsavedGuard } from "@/lib/unsaved";

type Pane = "draft" | "conversation";

/** Writing a Knowledge Base document with an agent: the draft beside the conversation (tabs on a phone). Nothing
 * reaches the Knowledge Base until Save to KB. */
export function DraftPage({ draftId, actions }: { draftId: string; actions?: (draft: KbDraft) => React.ReactNode }) {
  const client = useQueryClient();
  const query = useKbDraft(draftId);
  const { ask, dialog } = useConfirm();
  const [pane, setPane] = useState<Pane>("draft");
  const [target, setTarget] = useState<DraftTarget | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [title, setTitle] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pickAgent, setPickAgent] = useState(false);
  const draft = query.data;
  usePageTitle(draft ? draftTitle(draft.title) : null, "Knowledge Base");
  useUnsavedGuard(editing !== null && editing !== draft?.body_md, ask);

  if (isNotFound(query.error)) return <NotFoundView />;
  if (!draft) {
    return query.isError ? (
      <p role="alert" className="text-sm text-pink">{errorMessage(query.error)}</p>
    ) : (
      <p className="text-sm text-muted-foreground">Loading…</p>
    );
  }

  const busy = draft.state !== "idle";
  const name = draft.agent?.name ?? "The agent";

  /** Calls the draft's API; the draft it answers with replaces the cached one. */
  async function act(path: string, init?: { method?: string; json?: unknown }): Promise<boolean> {
    setError(null);
    try {
      const next = await api<KbDraft>(`/api/kb/drafts/${draftId}${path}`, { method: "POST", ...init });
      client.setQueryData(kbDraftKeys.one(draftId), next);
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.detail === "agent_not_available") setPickAgent(true);
      setError(errorMessage(err));
      return false;
    }
  }

  const startEditing = async () => {
    if (draft.open_marks > 0 && !(await act("/settle"))) return;
    setEditing((client.getQueryData<KbDraft>(kbDraftKeys.one(draftId)) ?? draft).body_md);
  };
  const doneEditing = async () => {
    if (editing !== null && editing !== draft.body_md && !(await act("", { method: "PUT", json: { body_md: editing } }))) return;
    setEditing(null);
  };
  const saveTitle = async () => {
    if (title !== null && title.trim() !== draft.title) await act("", { method: "PUT", json: { title: title.trim() } });
    setTitle(null);
  };

  const place = [draft.space.name, draft.folder_path].filter(Boolean).join(" › ");
  const draftPane = (
    <section aria-label="Draft" className="card min-w-0 space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        {editing === null ? (
          <Button variant="ghost" disabled={busy} onClick={startEditing}>
            Edit text
          </Button>
        ) : (
          <Button onClick={doneEditing}>Done editing</Button>
        )}
        {editing === null && draft.open_marks > 0 && (
          <span className="text-xs text-muted-foreground">Keeps the {draft.open_marks} open changes</span>
        )}
      </div>
      {busy && (
        <p className="rounded border border-amber/60 px-3 py-2 text-sm text-amber">
          {name} is writing… the draft is read-only until it finishes
        </p>
      )}
      {editing === null ? (
        <DraftView
          segments={draft.segments}
          busy={busy}
          onMark={(id, to) => void act(`/marks/${id}/${to}`)}
          onTarget={(t) => {
            setTarget(t);
            setPane("conversation");
          }}
        />
      ) : (
        <MarkdownField id="draft-body" value={editing} onChange={setEditing} />
      )}
    </section>
  );
  const conversationPane = (
    <section aria-label="Conversation with the agent" className="card min-w-0 p-4">
      <DraftConversation
        draft={draft}
        target={target}
        pickAgent={pickAgent}
        onClearTarget={() => setTarget(null)}
        onSend={async (text) => {
          const ok = await act("/requests", { json: { text, target } });
          if (ok) setTarget(null);
          return ok;
        }}
        onStop={() => void act("/stop")}
        onAgent={async (agentId) => {
          if (await act("/agent", { method: "PATCH", json: { agent_id: agentId } })) setPickAgent(false);
        }}
      />
    </section>
  );

  return (
    <div className="space-y-3">
      <header className="flex flex-wrap items-center gap-2">
        <p className="w-full font-mono text-xs text-muted-foreground">{place}</p>
        <input
          aria-label="Title"
          value={title ?? draft.title}
          placeholder="Untitled draft"
          maxLength={200}
          disabled={busy}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={saveTitle}
          className="min-w-0 flex-1 basis-48 rounded border border-transparent bg-transparent px-1 text-lg font-bold text-cyan-ink hover:border-line focus:border-cyan focus:outline-none"
        />
        <span className="rounded-full border border-cyan px-2 text-xs text-cyan-ink">Draft · not saved</span>
        {draft.open_marks > 0 && (
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">{draft.open_marks} changes from the last request</span>
            <Button variant="ghost" disabled={busy} onClick={() => void act("/keep-all")}>
              Keep all
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => void act("/undo-all")}>
              Undo all
            </Button>
          </span>
        )}
        {actions?.(draft)}
      </header>
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
      <div className="lg:hidden">
        <Tabs<Pane>
          label="Draft or conversation"
          tabs={[{ id: "draft", label: "Draft" }, { id: "conversation", label: "Conversation" }]}
          value={pane}
          onChange={setPane}
        />
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className={pane === "draft" ? "min-w-0" : "hidden min-w-0 lg:block"}>{draftPane}</div>
        <div className={pane === "conversation" ? "min-w-0" : "hidden min-w-0 lg:block"}>{conversationPane}</div>
      </div>
      {dialog}
    </div>
  );
}
