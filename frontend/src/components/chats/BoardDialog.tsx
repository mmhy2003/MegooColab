"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import type { BoardDefaults, Chat, ChatRound } from "@/lib/chats";
import { errorMessage } from "@/lib/errors";
import { useColumns } from "@/lib/project";

/** "Add this to the board?" after a round finishes or the chat ends: the round becomes an ordinary task with these
 * details (filled in from the chat, editable), or it stays a chat. */
export function BoardDialog({ chat, round }: { chat: Chat; round: ChatRound }) {
  const client = useQueryClient();
  const columns = useColumns(chat.project_key);
  const [open, setOpen] = useState(true);
  const [edits, setEdits] = useState<Partial<BoardDefaults>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const defaults = useQuery({
    queryKey: ["chats", "board", chat.id, round.n],
    queryFn: () => api<BoardDefaults>(`/api/chats/${chat.id}/rounds/${round.n}/board`),
  });
  const value = { ...defaults.data, ...edits } as BoardDefaults;
  const decide = async (add: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/chats/${chat.id}/rounds/${round.n}/board`, {
        method: "POST",
        json: add ? { add, title: value.title, description_md: value.description_md, column_id: value.column_id } : { add },
      });
      setOpen(false);
      await client.invalidateQueries({ queryKey: ["chats"] });
      if (add) await client.invalidateQueries({ queryKey: ["tasks"] });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onClose={() => setOpen(false)} title="Add this to the board?" wide>
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">
          A task records what was done, so it shows in the project&apos;s history and reports.
        </p>
        <div className="flex flex-col gap-1">
          <label htmlFor="board-title" className="text-xs tracking-wider text-muted-foreground uppercase">Title</label>
          <input
            id="board-title"
            value={value.title ?? ""}
            onChange={(e) => setEdits((x) => ({ ...x, title: e.target.value }))}
            className="rounded border border-line bg-surface-2 px-2 py-2 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="board-description" className="text-xs tracking-wider text-muted-foreground uppercase">Description</label>
          <textarea
            id="board-description"
            value={value.description_md ?? ""}
            onChange={(e) => setEdits((x) => ({ ...x, description_md: e.target.value }))}
            className="min-h-32 rounded border border-line bg-surface-2 p-2 text-sm"
          />
        </div>
        <Select label="Column" value={value.column_id ?? ""} onChange={(e) => setEdits((x) => ({ ...x, column_id: e.target.value }))}>
          {(columns.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" disabled={busy} onClick={() => void decide(false)}>No, just end it</Button>
          <Button disabled={busy || !value.title?.trim()} onClick={() => void decide(true)}>Create task</Button>
        </div>
      </div>
    </Dialog>
  );
}
