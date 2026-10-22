"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Select } from "@/components/ui/Select";
import type { Sprint } from "@/lib/types";

export function CompleteSprintDialog({
  sprint,
  openCount,
  planned,
  onConfirm,
  onClose,
}: {
  sprint: Sprint;
  openCount: number;
  planned: Sprint[];
  onConfirm: (moveOpenTo: string) => void;
  onClose: () => void;
}) {
  const ordered = [...planned].sort((a, b) => a.start_date.localeCompare(b.start_date));
  const [target, setTarget] = useState(ordered[0]?.id ?? "backlog");
  return (
    <Dialog open title={`Complete ${sprint.name}`} onClose={onClose}>
      <div className="space-y-4">
        <Select label={`Move ${openCount} open tasks to`} value={target} onChange={(e) => setTarget(e.target.value)}>
          {ordered.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
          <option value="backlog">Backlog</option>
        </Select>
        <Button onClick={() => onConfirm(target)}>Complete sprint</Button>
      </div>
    </Dialog>
  );
}
