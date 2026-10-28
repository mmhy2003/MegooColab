"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { memKeys } from "@/lib/memory";
import { useProjects } from "@/lib/project";

/** Adds a product entity (admins and managers) and the projects it relates to (MEM-1). */
export function ProductEditor() {
  const client = useQueryClient();
  const projects = useProjects();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return (
      <Button variant="ghost" onClick={() => setOpen(true)}>
        Add product
      </Button>
    );
  }
  return (
    <form
      className="card space-y-3 p-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          await api("/api/memory/products", {
            method: "POST",
            json: { name: name.trim(), description, project_ids: picked },
          });
          setOpen(false);
          setName("");
          setDescription("");
          setPicked([]);
          await client.invalidateQueries({ queryKey: memKeys.all });
        } catch (err) {
          setError(errorMessage(err));
        }
      }}
    >
      <Input label="Product name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
      <Input label="Description" maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
      <fieldset className="space-y-1">
        <legend className="text-xs tracking-wider text-muted-foreground uppercase">Projects</legend>
        {(projects.data ?? []).map((p) => (
          <label key={p.id} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={picked.includes(p.id)}
              onChange={(e) => setPicked(e.target.checked ? [...picked, p.id] : picked.filter((x) => x !== p.id))}
            />
            {p.key} — {p.name}
          </label>
        ))}
      </fieldset>
      {error && (
        <p role="alert" className="text-sm text-pink">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit">Create product</Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
