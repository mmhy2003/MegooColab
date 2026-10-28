"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { errorMessage } from "@/lib/errors";
import { useConfirm } from "@/components/ui/ConfirmDialog";

type Status = components["schemas"]["SearchAdminOut"];
const KEY = ["admin", "search"] as const;

/** Admin → Settings: whether search is up, how much is indexed, and a manual rebuild. */
export function SearchAdmin() {
  const { ask, dialog } = useConfirm();
  const client = useQueryClient();
  const status = useQuery({ queryKey: KEY, queryFn: () => api<Status>("/api/admin/search") });
  const [note, setNote] = useState<string | null>(null);
  const s = status.data;
  return (
    <>
      <section aria-label="Search" className="card space-y-2 p-4 text-sm">
        <h2 className="font-semibold">Search</h2>
        {status.error && <p className="text-pink">{errorMessage(status.error)}</p>}
        {s && (
          <>
            <p>
              <span className={s.available ? "text-cyan-ink" : "text-pink"}>{s.available ? "Available" : "Unavailable"}</span>
              {s.documents != null && <span className="text-muted-foreground"> · {s.documents.toLocaleString("en-US")} items indexed</span>}
            </p>
            <p className="text-xs text-muted-foreground">
              Last rebuilt: {s.last_rebuild_at ? new Date(s.last_rebuild_at).toLocaleString() : "never"}
            </p>
          </>
        )}
        <Button
          onClick={async () => {
            if (!(await ask({ title: "Rebuild the search index?", text: "It is rebuilt from the database in the background. Search keeps working while it runs.", ok: "Rebuild" }))) return;
            try {
              await api("/api/admin/search/rebuild", { method: "POST" });
              setNote("Rebuild queued. It runs in the background.");
            } catch (err) {
              setNote(errorMessage(err));
            }
            await client.invalidateQueries({ queryKey: KEY });
          }}
        >
          Rebuild index
        </Button>
        {note && <p className="text-xs text-muted-foreground">{note}</p>}
      </section>
      {dialog}
    </>
  );
}
