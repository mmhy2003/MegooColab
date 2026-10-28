import { FolderKanban } from "lucide-react";
import Link from "next/link";

import { Empty, Widget } from "@/components/dashboard/Widget";
import type { ProjectRow } from "@/lib/dashboard";

/** Projects in scope: progress (done green, in progress cyan), open tasks, and late ones in pink. */
export function ProjectsCard({ projects }: { projects: ProjectRow[] }) {
  return (
    <Widget title="Projects" icon={FolderKanban} more={{ href: "/projects", label: "All" }}>
      {projects.length === 0 ? (
        <Empty>No projects in scope.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {projects.map((p) => {
            const total = Math.max(1, p.open + p.done);
            return (
              <li key={p.key} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 py-1.5 text-sm">
                <Link href={`/projects/${p.key}/board`} className="w-10 shrink-0 font-mono text-xs text-cyan-ink no-underline hover:underline">
                  {p.key}
                </Link>
                <span className="min-w-0 flex-1 basis-20 truncate">{p.name}</span>
                <span
                  role="img"
                  aria-label={`${p.key}: ${p.done} done, ${p.in_progress} in progress, ${p.open - p.in_progress} to do`}
                  className="flex h-1.5 w-24 shrink-0 overflow-hidden rounded-sm bg-surface-2"
                >
                  <b className="block bg-green" style={{ width: `${(p.done / total) * 100}%` }} />
                  <b className="block bg-cyan" style={{ width: `${(p.in_progress / total) * 100}%` }} />
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {p.open} open
                  {p.late > 0 && (
                    <>
                      {" · "}
                      <span className="text-pink">{p.late} late</span>
                    </>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Widget>
  );
}
