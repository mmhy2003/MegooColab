"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { ImageGallery } from "@/components/images/ImageGallery";
import { TaskQuestions } from "@/components/questions/TaskQuestions";
import { ActivityThread } from "@/components/task/ActivityThread";
import { Attachments } from "@/components/task/Attachments";
import { Section } from "@/components/task/Section";
import { Subtasks } from "@/components/task/Subtasks";
import { Decisions } from "@/components/workflow/Decisions";
import { DocumentView } from "@/components/workflow/DocumentView";
import { MockupPanel } from "@/components/workflow/MockupPanel";
import { api } from "@/lib/api";
import type { Chat, ChatRound } from "@/lib/chats";
import { errorMessage } from "@/lib/errors";
import { useTask, useTasks, useUsers } from "@/lib/project";
import { qk } from "@/lib/queries";
import { useTaskQuestions } from "@/lib/questions";
import type { ActivityItem, Attachment } from "@/lib/types";
import { useMockups, useRunRecords, useWorkflow } from "@/lib/workflow";

/** One round of a chat (a task) laid out as a task's page is: the first message's images where a task has its
 * description, then its subtasks, mockups, design, plan, decisions, questions to other projects and attachments, and
 * last the conversation itself. The latest round shows every part, as a task does; an earlier one only those with
 * something in them, so a long chat stays short. Subtasks are the agent's plan steps: they open, but none is added
 * here. */
export function RoundSections({ chat, round, latest }: { chat: Chat; round: ChatRound; latest: boolean }) {
  const router = useRouter();
  const client = useQueryClient();
  const key = round.key;
  const projectKey = key.split("-")[0];
  const task = useTask(key);
  const all = useTasks(projectKey);
  const workflow = useWorkflow(key);
  const mockups = useMockups(key);
  const decisions = useRunRecords(key).data?.decisions.length ?? 0;
  const questions = useTaskQuestions(key);
  const attachments = useQuery({ queryKey: qk.attachments(key), queryFn: () => api<Attachment[]>(`/api/tasks/${key}/attachments`) });
  const activity = useQuery({
    queryKey: qk.activity(key),
    queryFn: () => api<ActivityItem[]>(`/api/tasks/${key}/activity?limit=200`),
  });
  const users = useUsers();
  const userNames = useMemo(() => new Map(users.data?.map((u) => [u.id, u.name])), [users.data]);
  const agentNames = useMemo(() => new Map(chat.agent ? [[chat.agent.id, chat.agent.name]] : []), [chat.agent]);
  const [error, setError] = useState<string | null>(null);

  const readOnly = !chat.can_act;
  const closed = readOnly || chat.status !== "open";
  const docs = workflow.data?.documents ?? [];
  const subtasks = task.data ? (all.data ?? []).filter((x) => x.parent_id === task.data.id && x.type === "subtask") : [];
  const files = attachments.data ?? [];
  // every part on the latest round; only the ones with something in them on an earlier one
  const shows = (has: boolean) => latest || has;
  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await client.invalidateQueries({ queryKey: qk.attachments(key) });
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="space-y-6">
      {(round.images ?? []).length > 0 && (
        <section aria-label="Images with the first message">
          <h3 className="text-xs tracking-wider text-muted-foreground uppercase">Images with the first message</h3>
          <ImageGallery images={round.images ?? []} />
        </section>
      )}
      {task.data && shows(subtasks.length > 0) && (
        <Section title={`Subtasks (${task.data.subtask_done_count}/${task.data.subtask_count})`}>
          <Subtasks
            subtasks={subtasks}
            disabled
            onOpen={(k) => router.push(`/projects/${projectKey}/tasks/${k.split("-")[1]}`)}
            onAdd={async () => undefined}
          />
        </Section>
      )}
      {(mockups.data?.length ?? 0) > 0 && (
        <Section id={latest ? "mockups" : undefined} title="Mockups">
          <MockupPanel taskKey={key} disabled={closed} />
        </Section>
      )}
      {(["design", "plan"] as const).map(
        (kind) =>
          docs.some((d) => d.kind === kind) && (
            // the latest round's documents keep the ids a thread link or the waiting button scrolls to
            <Section key={kind} id={latest ? `document-${kind}` : undefined} title={kind === "design" ? "Design" : "Plan"}>
              <DocumentView taskKey={key} kind={kind} disabled={closed} />
            </Section>
          ),
      )}
      {decisions > 0 && (
        <Section id={latest ? "decisions" : undefined} title={`Decisions (${decisions})`}>
          <Decisions taskKey={key} />
        </Section>
      )}
      {shows((questions.data?.length ?? 0) > 0) && <TaskQuestions taskKey={key} canAsk={!closed} />}
      {shows(files.length > 0) && (
        <Section title="Attachments">
          <Attachments
            items={files}
            names={userNames}
            disabled={closed}
            onUpload={async (file) => {
              const form = new FormData();
              form.append("file", file);
              await run(() => api(`/api/tasks/${key}/attachments`, { method: "POST", body: form }));
            }}
            onDelete={async (id) => {
              await run(() => api(`/api/attachments/${id}`, { method: "DELETE" }));
            }}
          />
        </Section>
      )}
      {error && <p role="alert" className="text-sm text-pink">{error}</p>}
      <Section title="Activity">
        <ActivityThread
          items={activity.data ?? []}
          columnNames={new Map()}
          userNames={userNames}
          agentNames={agentNames}
          taskKey={key}
          canAct={workflow.data?.can_act === true && chat.status === "open"}
          readOnly={readOnly}
        />
      </Section>
    </div>
  );
}
