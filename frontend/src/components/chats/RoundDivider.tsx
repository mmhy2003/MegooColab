"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/lib/api";
import type { ChatRound } from "@/lib/chats";
import { errorMessage } from "@/lib/errors";

/** The line between two rounds of a chat: which round, what it is about, and where its work starts from (the earlier
 * round's branch while that round's pull request is open), changeable until the branch is made. */
export function RoundDivider({ round, canEdit }: { round: ChatRound; canEdit: boolean }) {
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(round.branch_from ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    try {
      await api(`/api/tasks/${round.key}`, { method: "PATCH", json: { branch_from: value.trim() || null } });
      setEditing(false);
      await client.invalidateQueries({ queryKey: ["chats"] });
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2 py-2 text-xs text-muted-foreground">
      <span className="h-px flex-1 bg-line" aria-hidden />
      <span className="font-semibold text-fg">{`Round ${round.n} · ${round.title}`}</span>
      {editing ? (
        <form
          className="flex items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <input
            aria-label="Branch from"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="the default branch"
            className="rounded border border-line bg-surface-2 px-1.5 py-0.5 font-mono"
          />
          <button type="submit" className="text-cyan-ink">Save</button>
        </form>
      ) : (
        <>
          {round.branch_from && <span className="font-mono">{`from ${round.branch_from}`}</span>}
          {canEdit && !round.branch && (
            <button type="button" className="text-cyan-ink" onClick={() => setEditing(true)}>
              Change
            </button>
          )}
        </>
      )}
      {error && <span role="alert" className="text-pink">{error}</span>}
      <span className="h-px flex-1 bg-line" aria-hidden />
    </div>
  );
}
