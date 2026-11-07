"use client";

import { Plus } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useRef, useState } from "react";

import { ChatList } from "@/components/chats/ChatList";
import { ChatView } from "@/components/chats/ChatView";
import { NewChatDialog } from "@/components/chats/NewChatDialog";
import { ProjectPicker, type ProjectCounts } from "@/components/chats/ProjectPicker";
import { useFillWindow } from "@/components/task/fillWindow";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { CHAT_FILTERS, chatGroup, inFilter, useChats, type Chat, type ChatFilter } from "@/lib/chats";
import { errorMessage } from "@/lib/errors";
import { useProjects } from "@/lib/project";
import { useStoredState } from "@/lib/stored";

/** The Chats page (every project, with a filter) and a project's Chats tab (that project only): the chats down the
 * side, the open one beside them. On a phone, one or the other, and an open chat takes the whole screen (its ‹ goes
 * back to the list). They fill the window down to its bottom, so the page stays put: the list scrolls on its own, and
 * so does the open chat's conversation. */
export function ChatsPage(props: { projectKey?: string; chatId?: string }) {
  return (
    <Suspense>
      <Chats {...props} />
    </Suspense>
  );
}

function Chats({ projectKey, chatId }: { projectKey?: string; chatId?: string }) {
  const params = useSearchParams();
  const [adding, setAdding] = useState(params.get("new") === "1"); // the dashboard's New chat
  const projects = useProjects();
  // the projects picked on the Chats page (none: all), and which chats the list shows (Active, all but ended, first),
  // both kept in this browser
  const [picked, setPicked] = useStoredState<string[]>("chats.projects", [], "local");
  const [show, setShow] = useStoredState<ChatFilter>("chats.filter", "active", "local");
  // a project's tab asks for its chats; the Chats page takes them all and picks here
  const chats = useChats(projectKey);
  // a picked project no longer in view (deleted, or the viewer left its team) is ignored
  const known = useMemo(
    () => (projects.data ? picked.filter((k) => projects.data.some((p) => p.key === k)) : picked),
    [picked, projects.data],
  );
  const scoped = useMemo(
    () => (projectKey || known.length === 0 ? chats.data : chats.data?.filter((c) => known.includes(c.project_key))),
    [chats.data, projectKey, known],
  );
  const counts = useMemo(() => countByProject(chats.data ?? []), [chats.data]);
  const area = useRef<HTMLDivElement | null>(null);
  useFillWindow(area);
  const newChat = (
    <Button onClick={() => setAdding(true)}>
      <Plus size={14} aria-hidden /> New chat
    </Button>
  );
  return (
    <div className="space-y-4">
      {!projectKey && (
        <div className={chatId ? "max-md:hidden" : undefined}>
          <PageHeader title="Chats" subtitle="Talk to an agent about a project: it takes the work through design, plan, build and finish." actions={newChat} />
        </div>
      )}
      {/* one column that may shrink on a phone: a long title or link can't widen the page */}
      <div ref={area} className="grid grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)] gap-4 md:grid-cols-[18rem_minmax(0,1fr)]">
        <aside className={`card min-h-0 min-w-0 flex-col gap-3 p-3 ${chatId ? "hidden md:flex" : "flex"}`}>
          <div className="shrink-0">
            {projectKey ? (
              <div className="flex items-center gap-2">
                <h2 className="flex-1 text-base font-bold text-cyan-ink">Chats</h2>
                {newChat}
              </div>
            ) : (
              <ProjectPicker projects={projects.data ?? []} counts={counts} value={known} onChange={setPicked} />
            )}
          </div>
          {scoped && <StateFilter chats={scoped} value={show} onChange={setShow} />}
          {chats.error && <p role="alert" className="text-sm text-pink">{errorMessage(chats.error)}</p>}
          <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1">
            {scoped && (
              <ChatList
                chats={scoped.filter((c) => inFilter(c, show))}
                selected={chatId}
                showProject={!projectKey && known.length !== 1}
                empty={scoped.length ? CHAT_FILTERS.find((f) => f.value === show)?.empty : undefined}
              />
            )}
          </div>
        </aside>
        <section className={chatId ? "flex min-h-0 min-w-0 flex-col gap-2" : "hidden min-w-0 md:block"}>
          {chatId ? (
            <div className="min-h-0 flex-1">
              <ChatView chatId={chatId} />
            </div>
          ) : (
            <div className="card flex h-full min-h-60 items-center justify-center p-6 text-sm text-muted-foreground">
              Choose a chat, or start a new one.
            </div>
          )}
        </section>
      </div>
      {/* mounted only while open: the dialog opens itself on mount */}
      {adding && <NewChatDialog open onClose={() => setAdding(false)} projectKey={projectKey} />}
    </div>
  );
}

/** One tap per group of chats, each with how many it holds (of the chosen project's). */
function StateFilter({ chats, value, onChange }: { chats: Chat[]; value: ChatFilter; onChange: (f: ChatFilter) => void }) {
  return (
    <div role="group" aria-label="Show" className="flex shrink-0 flex-wrap gap-1.5">
      {CHAT_FILTERS.map((f) => {
        const on = f.value === value;
        return (
          <button
            key={f.value}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(f.value)}
            className={`inline-flex min-h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs ${
              on ? "border-cyan bg-cyan/10 text-cyan-ink" : "border-line text-muted-foreground hover:text-fg"
            }`}
          >
            {f.label}
            <span className={`text-[11px] ${on ? "" : "opacity-80"}`}>{chats.filter((c) => inFilter(c, f.value)).length}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Each project's chats, active (not ended) and all, for the project picker. */
function countByProject(chats: Chat[]): ProjectCounts {
  const out: ProjectCounts = new Map();
  for (const c of chats) {
    const n = out.get(c.project_key) ?? { active: 0, total: 0 };
    n.total += 1;
    if (chatGroup(c) !== "ended") n.active += 1;
    out.set(c.project_key, n);
  }
  return out;
}
