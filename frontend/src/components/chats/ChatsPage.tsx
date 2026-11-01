"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ChatList } from "@/components/chats/ChatList";
import { ChatView } from "@/components/chats/ChatView";
import { NewChatDialog } from "@/components/chats/NewChatDialog";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { useChats } from "@/lib/chats";
import { errorMessage } from "@/lib/errors";
import { useProjects } from "@/lib/project";

/** The Chats page (every project, with a filter) and a project's Chats tab (that project only): the chats down the
 * side, the open one beside them. On a phone, one or the other. */
export function ChatsPage(props: { projectKey?: string; chatId?: string }) {
  return (
    <Suspense>
      <Chats {...props} />
    </Suspense>
  );
}

function Chats({ projectKey, chatId }: { projectKey?: string; chatId?: string }) {
  const params = useSearchParams();
  const [filter, setFilter] = useState("");
  const [adding, setAdding] = useState(params.get("new") === "1"); // the dashboard's New chat
  const projects = useProjects();
  const project = projectKey ?? (filter || undefined);
  const chats = useChats(project);
  const newChat = (
    <Button onClick={() => setAdding(true)}>
      <Plus size={14} aria-hidden /> New chat
    </Button>
  );
  return (
    <div className="space-y-4">
      {!projectKey && (
        <PageHeader title="Chats" subtitle="Talk to an agent about a project: it takes the work through design, plan, build and finish." actions={newChat} />
      )}
      <div className="grid min-h-[60vh] gap-4 md:grid-cols-[18rem_minmax(0,1fr)]">
        <aside className={`card space-y-3 p-3 ${chatId ? "hidden md:block" : ""}`}>
          {projectKey ? (
            newChat
          ) : (
            <Select label="Project" value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">All projects</option>
              {(projects.data ?? []).map((p) => (
                <option key={p.id} value={p.key}>
                  {p.key} — {p.name}
                </option>
              ))}
            </Select>
          )}
          {chats.error && <p role="alert" className="text-sm text-pink">{errorMessage(chats.error)}</p>}
          {chats.data && <ChatList chats={chats.data} selected={chatId} showProject={!project} />}
        </aside>
        <section className={chatId ? "space-y-2" : "hidden md:block"}>
          {chatId && (
            <Link href={projectKey ? `/projects/${projectKey}/chats` : "/chats"} className="text-sm md:hidden">
              ← All chats
            </Link>
          )}
          {chatId ? (
            <ChatView chatId={chatId} />
          ) : (
            <div className="card flex h-full min-h-60 items-center justify-center p-6 text-sm text-muted-foreground">
              Choose a chat, or start a new one.
            </div>
          )}
        </section>
      </div>
      <NewChatDialog open={adding} onClose={() => setAdding(false)} projectKey={projectKey} />
    </div>
  );
}
