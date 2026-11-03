"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { api } from "@/lib/api";
import type { Chat } from "@/lib/chats";
import { errorMessage } from "@/lib/errors";

/** Ending the chat for good, for the End chat button and the phone's ⋯ menu. While the agent works it asks first:
 * ending stops it. Render `dialog` (the question) and `error` where the control is. */
export function useEndChat(chat: Chat, agentRunning: boolean) {
  const client = useQueryClient();
  const { ask, dialog } = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const end = async () => {
    if (agentRunning) {
      const ok = await ask({
        title: "End this chat?",
        text: "Stop the agent and end this chat? Whatever it committed stays on its branch.",
        ok: "End chat",
        tone: "warn",
      });
      if (!ok) return;
    }
    try {
      await api(`/api/chats/${chat.id}/end`, { method: "POST" });
      await client.invalidateQueries({ queryKey: ["chats"] });
    } catch (err) {
      setError(errorMessage(err));
    }
  };
  return { end, dialog, error };
}

/** Ends the chat for good. */
export function EndChatButton({ chat, agentRunning }: { chat: Chat; agentRunning: boolean }) {
  const { end, dialog, error } = useEndChat(chat, agentRunning);
  return (
    <>
      <Button variant="ghost" onClick={() => void end()}>
        End chat
      </Button>
      {error && <span role="alert" className="text-xs text-pink">{error}</span>}
      {dialog}
    </>
  );
}
