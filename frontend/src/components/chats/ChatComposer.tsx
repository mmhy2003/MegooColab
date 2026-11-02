"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ImageAttach, ImageDropZone } from "@/components/images/ImageAttach";
import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { intentText, type Chat } from "@/lib/chats";
import { errorMessage } from "@/lib/errors";
import { useImageDraft } from "@/lib/images";

/** The chat's message box. What a message does depends on what the chat waits for (an answer, changes to the
 * design or plan, a word to the working agent, a new round); the line under the box says which. */
export function ChatComposer({ chat, agentRunning }: { chat: Chat; agentRunning: boolean }) {
  const client = useQueryClient();
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const agentName = chat.agent?.name ?? "the agent";
  const images = useImageDraft(chat.takes_images ? undefined : `Update the runner on ${agentName}'s machine to send images.`);
  if (chat.status === "ended" || (chat.intent ?? "closed") === "closed") {
    return <p className="py-3 text-center text-sm text-muted-foreground">This chat has ended.</p>;
  }
  const agent = chat.agent?.name ?? "the agent";
  const send = async () => {
    if (!body.trim() || images.uploading) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/api/chats/${chat.id}/messages`, { method: "POST", json: { body, image_ids: images.ids } });
      setBody("");
      images.clear();
      await Promise.all([
        client.invalidateQueries({ queryKey: ["chats"] }),
        client.invalidateQueries({ queryKey: ["activity"] }),
        client.invalidateQueries({ queryKey: ["workflow"] }),
        client.invalidateQueries({ queryKey: ["documents"] }),
      ]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        void send();
      }}
    >
      <ImageDropZone draft={images}>
        <textarea
          aria-label={`Message ${agent}`}
          placeholder={`Message ${agent}…`}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit();
          }}
          className="block min-h-20 w-full rounded border border-line bg-surface-2 p-2 text-sm"
        />
      </ImageDropZone>
      <ImageAttach draft={images} />
      <div className="flex items-center gap-3">
        <p className="text-xs text-muted-foreground">{intentText(chat, agentRunning)}</p>
        <Button type="submit" className="ml-auto" disabled={busy || !body.trim() || images.uploading}>
          Send
        </Button>
      </div>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
    </form>
  );
}
