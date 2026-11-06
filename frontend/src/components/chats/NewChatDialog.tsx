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

const MODE_KEY = "megoo.newChatMode";
type Mode = "workflow" | "freestyle";
const MODES: { value: Mode; label: string; help: string }[] = [
  {
    value: "workflow",
    label: "Workflow",
    help: "Talks it through, writes a design and a plan for you to approve, builds it step by step with reviews, then finishes as the project is set up to.",
  },
  {
    value: "freestyle",
    label: "Freestyle",
    help: "Does what you ask, one reply at a time, with no design, plan or reviews. It can change files, switch branches, commit and push when you ask.",
  },
];

// the last choice is a per-viewer convenience: storage may be blocked, then it is Workflow
function rememberedMode(): Mode {
  try {
    return localStorage.getItem(MODE_KEY) === "freestyle" ? "freestyle" : "workflow";
  } catch {
    return "workflow";
  }
}

/** Start a chat: the project (fixed on a project's own tab), the agent (any free one by default), the message. */
export function NewChatDialog({ open, onClose, projectKey }: { open: boolean; onClose: () => void; projectKey?: string }) {
  const router = useRouter();
  const client = useQueryClient();
  const projects = useProjects();
  const [project, setProject] = useState(projectKey ?? "");
  const [agent, setAgent] = useState("");
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState<Mode>(rememberedMode);
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
        json: { project_key: project, agent_id: agent || null, message, image_ids: images.ids, mode },
      });
      try {
        localStorage.setItem(MODE_KEY, mode);
      } catch {
        // not remembered; the next chat starts as Workflow
      }
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
        <fieldset className="min-w-0 space-y-2">
          <legend className="mb-1 text-xs tracking-wider text-muted-foreground uppercase">How should the agent work?</legend>
          {MODES.map((m) => (
            <label
              key={m.value}
              className={`flex cursor-pointer gap-2.5 rounded-lg border bg-surface-2 p-2.5 ${
                mode === m.value ? "border-cyan shadow-[inset_0_0_0_1px_var(--cyan)]" : "border-line"
              }`}
            >
              <input
                type="radio"
                name="new-chat-mode"
                value={m.value}
                checked={mode === m.value}
                onChange={() => setMode(m.value)}
                className="mt-1 shrink-0 accent-cyan"
              />
              <span className="min-w-0">
                <span className="block text-sm font-semibold">{m.label}</span>
                <span className="block text-xs text-muted-foreground">{m.help}</span>
              </span>
            </label>
          ))}
        </fieldset>
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
