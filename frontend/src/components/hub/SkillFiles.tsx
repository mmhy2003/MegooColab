"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { useHubFile, type HubTool } from "@/lib/hub";

/** A skill's files; picking one shows its text. */
export function SkillFiles({ tool }: { tool: HubTool }) {
  const [open, setOpen] = useState<string | null>(null);
  const file = useHubFile(tool.id, open);
  return (
    <div className="space-y-2">
      <ul className="space-y-1">
        {(tool.files ?? []).map((f) => (
          <li key={f.path} className="flex items-center gap-2 text-sm">
            <button
              type="button"
              className={`font-mono text-xs hover:text-cyan-ink ${open === f.path ? "text-cyan-ink" : ""}`}
              aria-pressed={open === f.path}
              onClick={() => setOpen(open === f.path ? null : f.path)}
            >
              {f.path}
            </button>
            <span className="text-xs text-muted-foreground">{f.size} B</span>
            {f.runs_on && <Badge tone="amber">runs code</Badge>}
          </li>
        ))}
      </ul>
      {open && file.data && (
        file.data.text === null || file.data.text === undefined ? (
          <p className="text-sm text-muted-foreground">Can&apos;t show this file.</p>
        ) : (
          <pre data-scroll-x className="max-h-96 overflow-auto rounded bg-surface-2 p-2 text-xs">{file.data.text}</pre>
        )
      )}
    </div>
  );
}
