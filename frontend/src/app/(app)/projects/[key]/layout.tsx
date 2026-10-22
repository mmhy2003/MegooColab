"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

import { errorMessage } from "@/lib/errors";
import { useProject } from "@/lib/project";

export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const { key } = useParams<{ key: string }>();
  const pathname = usePathname();
  const project = useProject(key);

  if (project.error) {
    return (
      <div className="card mx-auto mt-10 max-w-md p-6 text-center">
        <p className="text-pink">{errorMessage(project.error)}</p>
        <Link href="/projects" className="mt-3 inline-block text-sm">Back to projects</Link>
      </div>
    );
  }
  if (!project.data) return null;
  const p = project.data;
  const tabs = [
    { href: `/projects/${p.key}/board`, label: "Board" },
    ...(p.sprints_enabled
      ? [
          { href: `/projects/${p.key}/backlog`, label: "Backlog" },
          { href: `/projects/${p.key}/reports`, label: "Reports" },
        ]
      : []),
    { href: `/projects/${p.key}/settings`, label: "Settings" },
  ];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-2 border-b border-line">
        <h1 className="pb-2 text-base font-bold">
          <span className="text-muted">{p.key}</span> <span className="text-cyan-ink glow-cyan">{p.name}</span>
        </h1>
        <nav aria-label="Project" className="flex gap-1">
          {tabs.map((t) => {
            const active = pathname.startsWith(t.href);
            return (
              <Link
                key={t.href}
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={`border-b-2 px-3 pb-2 text-sm no-underline ${active ? "border-cyan text-cyan-ink" : "border-transparent text-muted hover:text-fg"}`}
              >
                {t.label}
              </Link>
            );
          })}
        </nav>
      </div>
      {children}
    </div>
  );
}
