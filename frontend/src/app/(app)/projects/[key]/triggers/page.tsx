"use client";

import { useParams } from "next/navigation";

import { TriggerList } from "@/components/triggers/TriggerList";
import { useMe } from "@/lib/me";
import { useProject } from "@/lib/project";
import { projectRights } from "@/lib/rights";
import { usePageTitle } from "@/lib/title";

export default function ProjectTriggersPage() {
  const { key } = useParams<{ key: string }>();
  const project = useProject(key);
  const { data: me } = useMe();
  usePageTitle("Triggers", project.data?.name);
  if (!project.data) return null;
  return <TriggerList projectKey={project.data.key} canManage={projectRights(me, project.data).canManage} />;
}
