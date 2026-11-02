"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ImageAttach, ImageDropZone } from "@/components/images/ImageAttach";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Select } from "@/components/ui/Select";
import { useProjectAgents } from "@/lib/agents";
import { api } from "@/lib/api";
import type { Chat } from "@/lib/chats";
import { errorMessage } from "@/lib/errors";
import { useImageDraft } from "@/lib/images";
import { useProjects } from "@/lib/project";

/** Start a chat: the project (fixed on a project's own tab), the agent (any free one by default), the message. */
export function NewChatDialog({ open, onClose, projectKey }: { open: boolean; onClose: () => void; projectKey?: string }) {
  const router = useRouter();
  const client = useQueryClient();
  const projects = useProjects();
  const [project, setProject] = useState(projectKey ?? "");
  const [agent, setAgent] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const agents = useProjectAgents(project);
  const usable = (agents.data ?? []).filter((a) => a.can_use);
  // whether the chosen agent can be sent images is known only to the server: it says so when it can't
  const images = useImageDraft();

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const chat = await api<Chat>("/api/chats", {
        method: "POST",
        json: { project_key: project, agent_id: agent || null, message, image_ids: images.ids },
      });
      await client.invalidateQueries({ queryKey: ["chats"] });
      onClose();
      router.push(`/chats/${chat.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="New chat">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Select label="Project" value={project} disabled={!!projectKey} onChange={(e) => { setProject(e.target.value); setAgent(""); }}>
          {!projectKey && <option value="">Choose a project</option>}
          {projectKey && !projects.data?.some((p) => p.key === projectKey) && <option value={projectKey}>{projectKey}</option>}
          {(projects.data ?? []).map((p) => (
            <option key={p.id} value={p.key}>
              {p.key} — {p.name}
            </option>
          ))}
        </Select>
        <Select label="Agent" value={agent} disabled={!project} onChange={(e) => setAgent(e.target.value)}>
          <option value="">Any free agent</option>
          {usable.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </Select>
        <div className="flex flex-col gap-1">
          <label htmlFor="new-chat-message" className="text-xs tracking-wider text-muted-foreground uppercase">
            Message
          </label>
          <ImageDropZone draft={images}>
            <textarea
              id="new-chat-message"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="What should the agent do? For example: the login page throws on an empty email, fix it."
              className="block min-h-28 w-full rounded border border-line bg-surface-2 p-2 text-sm"
            />
          </ImageDropZone>
          <ImageAttach draft={images} />
        </div>
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy || !project || !message.trim() || images.uploading}>Start chat</Button>
        </div>
      </form>
    </Dialog>
  );
}
