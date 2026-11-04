"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { DiffView } from "@/components/kb/DiffView";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { ApiError, api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { kbKeys, type DiffOp } from "@/lib/kb";
import { kbDraftKeys, type KbDraft } from "@/lib/kbDrafts";

/** Save to KB: the draft becomes a revision credited to the person with the agent. When someone saved a newer
 * version meanwhile: see what changed, have the agent bring it in, or save over it. */
export function SaveDraftDialog({ draft, open, onClose }: { draft: KbDraft; open: boolean; onClose: () => void }) {
  const router = useRouter();
  const client = useQueryClient();
  const { ask, dialog } = useConfirm();
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [showDiff, setShowDiff] = useState(false);
  const doc = draft.document;
  const base = draft.base_revision ?? 0;
  const diff = useQuery({
    queryKey: kbKeys.diff(doc?.id ?? "", base, doc?.latest_revision ?? 0),
    queryFn: () => api<DiffOp[]>(`/api/kb/documents/${doc!.id}/revisions/${base}/diff/${doc!.latest_revision}`),
    enabled: showDiff && !!doc,
  });

  const save = async (force: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const saved = await api<{ document_id: string }>(`/api/kb/drafts/${draft.id}/save`, {
        method: "POST",
        json: { summary: summary.trim() || null, force },
      });
      // the draft is gone: leave its page before anything asks for it again
      router.push(`/kb/doc/${saved.document_id}`);
      onClose();
      await client.invalidateQueries({ queryKey: kbKeys.all });
      await client.invalidateQueries({ queryKey: kbDraftKeys.list() });
    } catch (err) {
      if (err instanceof ApiError && err.detail === "kb_conflict") {
        setConflict(true);
        // the draft names the latest revision only as of its last load
        await client.invalidateQueries({ queryKey: kbDraftKeys.one(draft.id) });
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  };

  const bringIn = async () => {
    setError(null);
    try {
      const next = await api<KbDraft>(`/api/kb/drafts/${draft.id}/bring-in`, { method: "POST" });
      client.setQueryData(kbDraftKeys.one(draft.id), next);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const saveOver = async () => {
    const ok = await ask({
      tone: "warn",
      title: "Save over the newer version?",
      text: "Their changes stay in the document's history, but the document becomes your draft.",
      ok: "Save over it",
      cancel: "Keep the draft",
    });
    if (ok) await save(true);
  };

  return (
    <Dialog open={open} onClose={onClose} title="Save to the Knowledge Base">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void save(false);
        }}
      >
        <Input
          label="Summary of change (optional)"
          maxLength={200}
          value={summary}
          placeholder={draft.agent ? `Written with ${draft.agent.name}` : undefined}
          onChange={(e) => setSummary(e.target.value)}
        />
        {draft.open_marks > 0 && (
          <p className="text-sm text-amber">{draft.open_marks} changes not reviewed</p>
        )}
        {conflict && (
          <div className="space-y-2 rounded border border-pink/60 p-3">
            <p className="text-sm text-pink">Someone saved a newer version.</p>
            <div className="flex flex-wrap gap-2">
              <Button variant="ghost" onClick={() => setShowDiff(true)}>
                Show what changed
              </Button>
              <Button variant="ghost" onClick={bringIn}>
                Ask the agent to bring it in
              </Button>
              <Button variant="danger" onClick={saveOver}>
                Save over it anyway
              </Button>
            </div>
            {showDiff && diff.data && <DiffView ops={diff.data} />}
          </div>
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
          <Button type="submit" disabled={busy || conflict}>
            Save
          </Button>
        </div>
      </form>
      {dialog}
    </Dialog>
  );
}

/** Discard draft: after a confirmation, the draft and its conversation are deleted. */
export function DiscardDraftButton({ draft }: { draft: KbDraft }) {
  const router = useRouter();
  const client = useQueryClient();
  const { ask, dialog } = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const discard = async () => {
    const ok = await ask({
      tone: "danger",
      title: "Discard this draft?",
      text: "The draft and its conversation are deleted.",
      ok: "Discard",
    });
    if (!ok) return;
    try {
      await api(`/api/kb/drafts/${draft.id}`, { method: "DELETE" });
      // the draft is gone: leave its page before anything asks for it again
      router.push(draft.document ? `/kb/doc/${draft.document.id}` : `/kb/${draft.space.id}`);
      await client.invalidateQueries({ queryKey: kbDraftKeys.list() });
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  return (
    <>
      <Button variant="danger" onClick={discard}>
        Discard draft
      </Button>
      {error && (
        <span role="alert" className="text-sm text-pink">
          {error}
        </span>
      )}
      {dialog}
    </>
  );
}
