"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { HubTool } from "@/lib/hub";

/** A skill's files, as a .zip or as a folder (each file sent under its path inside the folder). */
export function SkillUpload({ toolId, onDone }: { toolId?: string; onDone: (tool: HubTool) => void }) {
  const zip = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async (form: FormData) => {
    setError(null);
    setBusy(true);
    try {
      const url = toolId ? `/api/hub/tools/${toolId}/files` : "/api/hub/skills";
      onDone(await api<HubTool>(url, { method: toolId ? "PUT" : "POST", body: form }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Button variant="ghost" disabled={busy} onClick={() => zip.current?.click()}>Upload a .zip</Button>
        <Button variant="ghost" disabled={busy} onClick={() => folder.current?.click()}>Upload a folder</Button>
      </div>
      <input
        ref={zip}
        type="file"
        accept=".zip"
        aria-label="Upload a .zip"
        className="sr-only"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) return;
          const form = new FormData();
          form.append("file", file);
          await send(form);
        }}
      />
      <input
        ref={folder}
        type="file"
        multiple
        aria-label="Upload a folder"
        className="sr-only"
        {...{ webkitdirectory: "" }}
        onChange={async (e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = "";
          if (files.length === 0) return;
          const form = new FormData();
          for (const f of files) form.append("files", f, f.webkitRelativePath || f.name);
          await send(form);
        }}
      />
      <p className="text-xs text-muted-foreground">A skill is a folder with a SKILL.md at its top. Up to 100 files, 2 MB in all.</p>
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
    </div>
  );
}
