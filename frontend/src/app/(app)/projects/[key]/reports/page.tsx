"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";

import { BurndownChart } from "@/components/sprint/BurndownChart";
import { VelocityChart } from "@/components/sprint/VelocityChart";
import { api } from "@/lib/api";
import { useProject, useSprints } from "@/lib/project";
import { qk } from "@/lib/queries";
import type { BurndownPoint, VelocityPoint } from "@/lib/types";

export default function ReportsPage() {
  const { key } = useParams<{ key: string }>();
  const project = useProject(key);
  const sprints = useSprints(key, project.data?.sprints_enabled ?? false);
  const candidates = (sprints.data ?? []).filter((s) => s.state !== "planned");
  const active = candidates.find((s) => s.state === "active");
  const [picked, setPicked] = useState<string | null>(null);
  const sprintId = picked ?? active?.id ?? candidates.at(-1)?.id ?? null;
  const sprint = candidates.find((s) => s.id === sprintId);

  const burndown = useQuery({
    queryKey: qk.burndown(sprintId ?? "none"),
    queryFn: () => api<BurndownPoint[]>(`/api/sprints/${sprintId}/burndown`),
    enabled: Boolean(sprintId),
  });
  const velocity = useQuery({
    queryKey: qk.velocity(key),
    queryFn: () => api<VelocityPoint[]>(`/api/projects/${key}/velocity`),
    enabled: project.data?.sprints_enabled ?? false,
  });

  if (!project.data) return null;
  return (
    <div className="space-y-4">
      {candidates.length > 0 && (
        <select
          aria-label="Sprint"
          className="rounded border border-line bg-surface-2 px-2 py-1.5 text-sm"
          value={sprintId ?? ""}
          onChange={(e) => setPicked(e.target.value)}
        >
          {candidates.map((s) => (
            <option key={s.id} value={s.id}>{s.name}{s.state === "active" ? " (active)" : ""}</option>
          ))}
        </select>
      )}
      {sprint ? (
        <BurndownChart points={burndown.data ?? []} sprintName={sprint.name} />
      ) : (
        <p className="card p-6 text-sm text-muted-foreground">No sprint has started yet.</p>
      )}
      <VelocityChart points={velocity.data ?? []} />
    </div>
  );
}
