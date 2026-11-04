"use client";

import { useParams } from "next/navigation";

import { CronList } from "@/components/crons/CronList";
import { useMe } from "@/lib/me";
import { useProject } from "@/lib/project";
import { projectRights } from "@/lib/rights";
import { usePageTitle } from "@/lib/title";

export default function ProjectCronsPage() {
  const { key } = useParams<{ key: string }>();
  const project = useProject(key);
  const { data: me } = useMe();
  usePageTitle("Crons", project.data?.name);
  if (!project.data) return null;
  return <CronList projectKey={project.data.key} canManage={projectRights(me, project.data).canManage} />;
}
