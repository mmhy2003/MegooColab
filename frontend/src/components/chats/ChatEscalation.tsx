"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { EscalationActions, type EscalationAction } from "@/components/workflow/EscalationActions";
import { api, ApiError } from "@/lib/api";
import { chatKeys, type Chat, type ChatRound } from "@/lib/chats";
import { errorMessage } from "@/lib/errors";
import { qk } from "@/lib/queries";
import { useWorkflow } from "@/lib/workflow";

/** The latest round stopped on an escalation: why, and the same Retry, Accept and Pause as a task's workflow panel,
 * at the end of the conversation. A round has no task page of its own, so this is the only place to decide it. */
export function ChatEscalation({ chat, round }: { chat: Chat; round: ChatRound }) {
  const client = useQueryClient();
  const workflow = useWorkflow(round.key);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wf = workflow.data;
  if (!wf || wf.status !== "waiting_human" || wf.needs !== "escalation") return null;

  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: qk.workflow(round.key) }),
      client.invalidateQueries({ queryKey: qk.agentRuns(round.key) }),
      client.invalidateQueries({ queryKey: qk.activity(round.key) }),
      client.invalidateQueries({ queryKey: chatKeys.one(chat.id) }),
      client.invalidateQueries({ queryKey: ["chats"] }),
    ]);
  const decide = async (action: EscalationAction) => {
    setError(null);
    setBusy(true);
    try {
      await api(`/api/tasks/${round.key}/workflow/escalation`, { method: "POST", json: { action } });
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
      if (err instanceof ApiError && err.status === 409) await refresh(); // decided elsewhere meanwhile
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Escalation" className="space-y-1 text-sm">
      <EscalationActions
        wf={wf}
        canDecide={chat.can_act && chat.status === "open" && wf.can_act}
        busy={busy}
        onDecide={(action) => void decide(action)}
      />
      {error && <p role="alert" className="text-xs text-pink">{error}</p>}
    </section>
  );
}
