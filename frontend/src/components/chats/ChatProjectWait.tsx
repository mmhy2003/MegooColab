"use client";

import { useQueryClient } from "@tanstack/react-query";

import { ProjectWaitBanner } from "@/components/questions/ProjectWaitBanner";
import { chatKeys, type Chat, type ChatRound } from "@/lib/chats";
import { qk } from "@/lib/queries";
import { questionKeys } from "@/lib/questions";
import { useWorkflow } from "@/lib/workflow";

/** The latest round waits for other projects' answers: the same banner as a task's workflow panel, at the end of
 * the conversation (a round has no task page of its own). */
export function ChatProjectWait({ chat, round }: { chat: Chat; round: ChatRound }) {
  const client = useQueryClient();
  const workflow = useWorkflow(round.key);
  const wf = workflow.data;
  if (!wf || wf.status !== "waiting_human" || wf.needs !== "project_answer") return null;
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: qk.workflow(round.key) }),
      client.invalidateQueries({ queryKey: qk.agentRuns(round.key) }),
      client.invalidateQueries({ queryKey: qk.activity(round.key) }),
      client.invalidateQueries({ queryKey: chatKeys.one(chat.id) }),
      client.invalidateQueries({ queryKey: ["chats"] }),
      client.invalidateQueries({ queryKey: questionKeys.all }),
    ]);
  return (
    <ProjectWaitBanner
      taskKey={round.key}
      waits={wf.project_waits ?? []}
      canAct={chat.can_act}
      agentName={chat.agent?.name}
      inChat
      onChanged={refresh}
    />
  );
}
