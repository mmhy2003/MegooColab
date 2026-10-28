"use client";

import { ChevronsUpDown } from "lucide-react";
import { useState } from "react";

import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/shadcn/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/shadcn/popover";
import type { ProjectAgent, Task, User } from "@/lib/types";

const AGENT_DENIED = "Only the owner, project managers and admins can assign this agent";

type Patch = { assignee_user_id?: string | null; assignee_agent_id?: string | null };

/**
 * The task's assignee: a searchable list of people and agents, opened like a dropdown (no blur; a click outside or
 * Escape closes it, and Escape stays inside, so the task drawer around it stays open).
 */
export function AssigneePicker({
  task,
  users,
  agents,
  disabled,
  onPatch,
}: {
  task: Task;
  users: User[];
  agents: ProjectAgent[];
  disabled?: boolean;
  onPatch: (patch: Patch) => void;
}) {
  const [open, setOpen] = useState(false);
  const people = users.filter((u) => u.status !== "deactivated" || u.id === task.assignee_user_id);
  // an agent assigned before but no longer bound to the project still shows, unselectable
  const gone = task.assignee_agent && !agents.some((a) => a.id === task.assignee_agent_id) ? task.assignee_agent : null;
  const current = task.assignee_agent_id
    ? (agents.find((a) => a.id === task.assignee_agent_id)?.name ?? task.assignee_agent?.name)
    : task.assignee_user_id
      ? users.find((u) => u.id === task.assignee_user_id)?.name
      : undefined;

  const choose = (patch: Patch) => {
    onPatch(patch);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          // eslint-disable-next-line jsx-a11y/role-has-required-aria-props -- PopoverTrigger adds aria-controls
          role="combobox"
          aria-label="Assignee"
          aria-expanded={open}
          disabled={disabled}
          className="flex w-full items-center justify-between gap-2 rounded border border-line bg-surface-2 px-2 py-1 text-left text-sm disabled:opacity-60"
        >
          <span className={`min-w-0 truncate ${current ? "" : "text-muted-foreground"}`}>{current ?? "Unassigned"}</span>
          <ChevronsUpDown size={14} aria-hidden className="shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        collisionPadding={8}
        className="w-(--radix-popover-trigger-width) min-w-56 p-0"
        onEscapeKeyDown={(e) => e.stopPropagation()} // the drawer's own Escape must not see it
      >
        <Command>
          <CommandInput placeholder="Search people and agents" />
          <CommandList>
            <CommandEmpty>No one matches.</CommandEmpty>
            <CommandItem value="Unassigned" onSelect={() => choose({ assignee_user_id: null, assignee_agent_id: null })}>
              Unassigned
            </CommandItem>
            <CommandGroup heading="People">
              {people.map((u) => (
                <CommandItem key={u.id} value={`${u.name} user:${u.id}`} onSelect={() => choose({ assignee_user_id: u.id })}>
                  {u.name}
                </CommandItem>
              ))}
            </CommandGroup>
            {(agents.length > 0 || gone) && (
              <CommandGroup heading="Agents">
                {agents.map((a) => (
                  <CommandItem
                    key={a.id}
                    value={`${a.name} agent:${a.id}`}
                    disabled={!a.can_use}
                    title={a.can_use ? undefined : AGENT_DENIED}
                    onSelect={() => choose({ assignee_agent_id: a.id })}
                  >
                    {a.name}
                  </CommandItem>
                ))}
                {gone && (
                  <CommandItem value={`${gone.name} agent:${gone.id}`} disabled>
                    {gone.name}
                  </CommandItem>
                )}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
