"use client";

import { Activity, BarChart3, Bot, FolderKanban, GitBranch, History, Inbox, UserRoundCheck } from "lucide-react";
import { useState } from "react";

import { AgentsCard } from "@/components/dashboard/AgentsCard";
import { FinishedChart } from "@/components/dashboard/FinishedChart";
import { Kpis } from "@/components/dashboard/Kpis";
import { MyTasks } from "@/components/dashboard/MyTasks";
import { NeedsYou } from "@/components/dashboard/NeedsYou";
import { ProjectsCard } from "@/components/dashboard/ProjectsCard";
import { RecentActivity } from "@/components/dashboard/RecentActivity";
import { RunningNow } from "@/components/dashboard/RunningNow";
import { ScopeSwitch } from "@/components/dashboard/ScopeSwitch";
import { StageBars } from "@/components/dashboard/StageBars";
import { SystemCard } from "@/components/dashboard/SystemCard";
import { Widget } from "@/components/dashboard/Widget";
import { PageHeader } from "@/components/ui/PageHeader";
import { type DashboardScope, readScope, useDashboard, writeScope } from "@/lib/dashboard";
import type { User } from "@/lib/types";

/** The home page (layout A): headline numbers; what needs you and your tasks beside what the agents are doing; then
 * the work in numbers, two columns wide; then System for admins. One column on narrow screens. */
export function Dashboard({ user }: { user: User }) {
  const isAdmin = user.role === "admin";
  const [chosen, setScope] = useState<DashboardScope>(() => readScope(isAdmin));
  // Everything is for admins: someone who lost the role mid-session drops back to My teams
  const scope = chosen === "all" && !isAdmin ? "teams" : chosen;
  const { data, isError } = useDashboard(scope, isAdmin);
  const choose = (s: DashboardScope) => {
    setScope(s);
    writeScope(s);
  };
  return (
    <div className="space-y-3">
      <PageHeader title="Dashboard" subtitle="Updates live" actions={<ScopeSwitch value={scope} onChange={choose} isAdmin={isAdmin} />} />
      {isError && !data && (
        <p role="alert" className="text-sm text-pink">
          The dashboard could not load. Reload the page to try again.
        </p>
      )}
      {data ? <Kpis numbers={data.numbers} /> : <div aria-hidden className="h-20 animate-pulse rounded bg-surface-2" />}
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div className="grid min-w-0 content-start gap-3">
          {data ? (
            <NeedsYou items={data.needs} total={data.numbers.need_you} showWaitingFor={scope !== "mine"} />
          ) : (
            <Widget title="Needs you" icon={Inbox} loading />
          )}
          {data ? <MyTasks items={data.my_tasks} /> : <Widget title="My tasks" icon={UserRoundCheck} loading />}
        </div>
        <div className="grid min-w-0 content-start gap-3">
          {data ? (
            <RunningNow running={data.running} queued={data.queued} isAdmin={isAdmin} />
          ) : (
            <Widget title="Running now" icon={Activity} loading />
          )}
          {data ? <AgentsCard agents={data.agents} isAdmin={isAdmin} /> : <Widget title="Agents" icon={Bot} loading />}
        </div>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {data ? <StageBars stages={data.stages} /> : <Widget title="Workflows by stage" icon={GitBranch} loading />}
        {data ? (
          <FinishedChart days={data.finished_daily} />
        ) : (
          <Widget title="Tasks finished · last 14 days" icon={BarChart3} loading />
        )}
        {data ? <ProjectsCard projects={data.projects} /> : <Widget title="Projects" icon={FolderKanban} loading />}
        {data ? <RecentActivity rows={data.activity} /> : <Widget title="Recent activity" icon={History} loading />}
      </div>
      {data?.system && <SystemCard system={data.system} />}
    </div>
  );
}
