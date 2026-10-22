"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input, Textarea } from "@/components/ui/Input";
import { errorMessage } from "@/lib/errors";

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function NewSprintDialog({
  suggestedName,
  onCreate,
  onClose,
}: {
  suggestedName: string;
  onCreate: (body: { name: string; goal: string; start_date: string; end_date: string }) => Promise<void>;
  onClose: () => void;
}) {
  const today = new Date();
  const [form, setForm] = useState({
    name: suggestedName,
    goal: "",
    start_date: isoDate(today),
    end_date: isoDate(new Date(today.getTime() + 13 * 86_400_000)),
  });
  const [error, setError] = useState<string | null>(null);
  return (
    <Dialog open title="New sprint" onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          if (form.end_date < form.start_date) return setError("The end date must be on or after the start date.");
          try {
            await onCreate(form);
            onClose();
          } catch (err) {
            setError(errorMessage(err));
          }
        }}
      >
        <Input label="Name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Textarea label="Goal" value={form.goal} onChange={(e) => setForm({ ...form, goal: e.target.value })} />
        <div className="grid grid-cols-2 gap-3">
          <Input label="Start" type="date" required value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
          <Input label="End" type="date" required value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
        </div>
        {error && <p role="alert" className="text-sm text-pink">{error}</p>}
        <Button type="submit">Create sprint</Button>
      </form>
    </Dialog>
  );
}
