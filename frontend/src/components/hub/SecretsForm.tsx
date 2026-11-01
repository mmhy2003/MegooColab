"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { hubKeys, type HubTool } from "@/lib/hub";

/** A tool's secret values: written here, never shown again. Only the fields typed into are sent. */
export function SecretsForm({ tool }: { tool: HubTool }) {
  const client = useQueryClient();
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  if (tool.secrets.length === 0) return <p className="text-sm text-muted-foreground">This tool has no secrets.</p>;
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        setSaved(false);
        const typed = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== ""));
        if (Object.keys(typed).length === 0) return;
        try {
          await api(`/api/hub/tools/${tool.id}/secrets`, { method: "PUT", json: { values: typed } });
          setValues({});
          setSaved(true);
          await client.invalidateQueries({ queryKey: hubKeys.all });
        } catch (err) {
          setError(errorMessage(err));
        }
      }}
    >
      {tool.secrets.map((s) => (
        <div key={s.name} className="flex items-end gap-2">
          <div className="flex-1">
            <Input
              label={s.name}
              type="password"
              autoComplete="off"
              value={values[s.name] ?? ""}
              placeholder={s.set ? "Leave empty to keep" : "Not set"}
              onChange={(e) => setValues({ ...values, [s.name]: e.target.value })}
              maxLength={4000}
            />
          </div>
          <span className={`pb-2 text-xs ${s.set ? "text-green-ink" : "text-amber"}`}>{s.set ? "set" : "not set"}</span>
        </div>
      ))}
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      {saved && <p role="status" className="text-sm text-green-ink">Saved.</p>}
      <Button type="submit">Save secrets</Button>
    </form>
  );
}
