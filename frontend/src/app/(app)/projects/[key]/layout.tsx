"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

import { StatusBanner } from "@/components/project/StatusBanner";
import { NotFoundView } from "@/components/shell/NotFound";
import { ScrollX } from "@/components/ui/ScrollX";
import { errorMessage, isNotFound } from "@/lib/errors";
import { canManage, useMe } from "@/lib/me";
import { useProject } from "@/lib/project";
import { useQuestions } from "@/lib/questions";
import { usePageTitle } from "@/lib/title";
import { useTrail } from "@/lib/trail";

/** Questions other projects asked this one that need a person to answer. */
/** The project's incoming questions: a link beside the tabs on a wide screen; on a phone the tab bar's last item
 * ("Questions"), so it takes no row of its own. Either way it opens the Questions page, so it is never the current tab. */
function IncomingQuestions({ projectKey, variant }: { projectKey: string; variant: "tab" | "link" }) {
  const waiting = useQuestions("incoming", projectKey, "needs_human").data?.length ?? 0;
  const tab = variant === "tab";
  return (
    <Link
      href={`/questions?tab=incoming&project=${projectKey}`}
      className={
        tab
          ? "shrink-0 border-b-2 border-transparent px-3 pb-2 text-sm whitespace-nowrap text-muted-foreground no-underline hover:text-fg md:hidden"
          : "ml-auto pb-2 text-sm text-muted-foreground no-underline hover:text-fg max-md:hidden"
      }
    >
      {tab ? "Questions" : "Incoming questions"}
      {waiting > 0 && (
        <span className="ml-1.5 rounded-full border border-pink px-1.5 text-xs text-pink" aria-label={`${waiting} need an answer`}>
          {waiting}
        </span>
      )}
    </Link>
  );
}

const TAB_TITLES: Record<string, string> = { board: "Board", chats: "Chats", backlog: "Backlog", reports: "Reports", settings: "Settings" };

export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const { key } = useParams<{ key: string }>();
  const pathname = usePathname();
  const project = useProject(key);
  const { data: me } = useMe();
  // "PAY Board"; a task page's own title (the task) is set over it by TaskView
  const tab = TAB_TITLES[pathname.split("/")[3] ?? ""];
  usePageTitle([project.data?.key ?? key.toUpperCase(), tab].filter(Boolean).join(" "));
  // "Projects › Payments › Board"; a task names itself over it (TaskView)
  useTrail([
    { label: "Projects", href: "/projects" },
    { label: project.data?.name ?? null, href: `/projects/${key.toUpperCase()}/board` },
    ...(tab ? [{ label: tab }] : []),
  ]);

  if (isNotFound(project.error)) return <NotFoundView />;
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
    { href: `/projects/${p.key}/chats`, label: "Chats" },
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
        {/* on a phone the name keeps to one line, cut short; the whole of it shows on hover */}
        <h1 title={`${p.key} ${p.name}`} className="pb-2 text-base font-bold max-md:w-full max-md:truncate">
          <span className="text-muted-foreground">{p.key}</span> <span className="text-cyan-ink glow-cyan">{p.name}</span>
        </h1>
        {/* on a narrow phone the tabs scroll sideways instead of widening the page, the edge faded where more hide */}
        <ScrollX as="nav" label="Project" chevron className="max-w-full" innerClassName="flex gap-1">
          {tabs.map((t) => {
            const active = pathname.startsWith(t.href);
            return (
              <Link
                key={t.href}
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={`shrink-0 border-b-2 px-3 pb-2 text-sm whitespace-nowrap no-underline ${active ? "border-cyan text-cyan-ink" : "border-transparent text-muted-foreground hover:text-fg"}`}
              >
                {t.label}
              </Link>
            );
          })}
          <IncomingQuestions projectKey={p.key} variant="tab" />
        </ScrollX>
        <IncomingQuestions projectKey={p.key} variant="link" />
      </div>
      <StatusBanner project={p} canChange={canManage(me)} />
      {children}
    </div>
  );
}
