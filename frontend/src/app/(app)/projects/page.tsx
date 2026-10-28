"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { canManage, useMe } from "@/lib/me";
import { useProjects } from "@/lib/project";
import { readShowArchived, STATUS_LABEL, writeShowArchived } from "@/lib/projectStatus";

export default function ProjectsPage() {
  const { data: me } = useMe();
  const projects = useProjects();
  const [showArchived, setShowArchived] = useState(readShowArchived);
  const all = projects.data ?? [];
  const shown = showArchived ? all : all.filter((p) => p.status !== "archived");
  return (
    <div>
      <PageHeader
        title="Projects"
        actions={
          canManage(me) && (
            <Link href="/projects/new" className="no-underline">
              <Button>
                <Plus size={14} aria-hidden /> New project
              </Button>
            </Link>
          )
        }
      />
      {all.some((p) => p.status === "archived") && (
        <label className="mb-3 flex w-fit items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => {
              setShowArchived(e.target.checked);
              writeShowArchived(e.target.checked);
            }}
          />
          Show archived
        </label>
      )}
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {shown.map((p) => (
          <Link key={p.id} href={`/projects/${p.key}/board`} className={`card block p-4 text-fg no-underline hover:glow-box ${p.status === "archived" ? "opacity-70" : ""}`}>
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              {p.key}
              {p.status !== "active" && (
                <span className="rounded-sm border border-current px-1.5 text-[11px] text-amber">{STATUS_LABEL[p.status]}</span>
              )}
            </p>
            <h2 className="text-sm text-cyan-ink">{p.name}</h2>
            {p.description && <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{p.description}</p>}
          </Link>
        ))}
      </div>
      {projects.data && shown.length === 0 && all.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No projects yet.{canManage(me) ? " Create one to get started." : " Ask a manager to add your team to a project."}
        </p>
      )}
    </div>
  );
}
