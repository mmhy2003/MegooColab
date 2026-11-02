"use client";

import { MoreHorizontal, Pencil, Trash2, UserCheck } from "lucide-react";
import { useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/shadcn/dropdown-menu";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api";
import { ANSWER_MODE_HELP } from "@/lib/agents";
import { errorMessage } from "@/lib/errors";
import type { Agent, AnswerMode } from "@/lib/types";

function RenameDialog({ agent, onClose, onSaved }: { agent: Agent; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(agent.name);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open title="Rename agent" onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await api(`/api/agents/${agent.id}`, { method: "PATCH", json: { name: name.trim() } });
            onSaved();
          } catch (err) {
            setError(errorMessage(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required data-autofocus />
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy || !name.trim()}>Save</Button>
        </div>
      </form>
    </Dialog>
  );
}

function AnswerModeDialog({ agent, onClose, onSaved }: { agent: Agent; onClose: () => void; onSaved: () => void }) {
  const [mode, setMode] = useState<AnswerMode>(agent.answer_mode);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog open title="Answer mode" onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await api(`/api/agents/${agent.id}`, { method: "PATCH", json: { answer_mode: mode } });
            onSaved();
          } catch (err) {
            setError(errorMessage(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <div>
          <Select label="Answer mode" value={mode} onChange={(e) => setMode(e.target.value as AnswerMode)}>
            <option value="manual">Manual</option>
            <option value="auto">Auto</option>
          </Select>
          <p className="mt-1 text-xs text-muted-foreground">{ANSWER_MODE_HELP[mode]}</p>
        </div>
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy}>Save</Button>
        </div>
      </form>
    </Dialog>
  );
}

/** An agent's ⋯ menu: Rename, Answer mode and Delete. */
export function AgentMenu({
  agent,
  onChanged,
  onDeleted,
  onError,
}: {
  agent: Agent;
  onChanged: () => void;
  onDeleted: () => void;
  onError: (message: string) => void;
}) {
  const { ask, dialog } = useConfirm();
  const [open, setOpen] = useState<"rename" | "answer" | null>(null);
  const saved = () => {
    setOpen(null);
    onChanged();
  };
  return (
    <>
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <button type="button" className="icon-btn" aria-label={`Actions for ${agent.name}`}>
            <MoreHorizontal size={16} aria-hidden />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" collisionPadding={8} className="w-48">
          <DropdownMenuItem onSelect={() => setOpen("rename")}>
            <Pencil size={14} aria-hidden />
            Rename
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setOpen("answer")}>
            <UserCheck size={14} aria-hidden />
            Answer mode
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={async () => {
              if (!(await ask({ tone: "danger", title: `Delete ${agent.name}?`, text: "Its runner stops taking work for it, and it is unassigned from its tasks.", ok: "Delete" }))) return;
              try {
                await api(`/api/agents/${agent.id}`, { method: "DELETE" });
                onDeleted();
              } catch (err) {
                onError(errorMessage(err));
              }
            }}
          >
            <Trash2 size={14} aria-hidden />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {open === "rename" && <RenameDialog agent={agent} onClose={() => setOpen(null)} onSaved={saved} />}
      {open === "answer" && <AnswerModeDialog agent={agent} onClose={() => setOpen(null)} onSaved={saved} />}
      {dialog}
    </>
  );
}
