"use client";

import { Plus } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { canManage, useMe } from "@/lib/me";
import { useProjects } from "@/lib/project";

export default function ProjectsPage() {
  const { data: me } = useMe();
  const projects = useProjects();
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
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {projects.data?.map((p) => (
          <Link key={p.id} href={`/projects/${p.key}/board`} className="card block p-4 text-fg no-underline hover:glow-box">
            <p className="text-xs text-muted">{p.key}</p>
            <h2 className="text-sm text-cyan-ink">{p.name}</h2>
            {p.description && <p className="mt-1 line-clamp-2 text-sm text-muted">{p.description}</p>}
          </Link>
        ))}
      </div>
      {projects.data?.length === 0 && (
        <p className="text-sm text-muted">
          No projects yet.{canManage(me) ? " Create one to get started." : " Ask a manager to add your team to a project."}
        </p>
      )}
    </div>
  );
}
