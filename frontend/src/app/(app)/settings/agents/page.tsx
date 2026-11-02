"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useState } from "react";

import { AddAgentDialog } from "@/components/agents/AddAgentDialog";
import { AgentsTab } from "@/components/agents/AgentsTab";
import { usableRunnerTokens } from "@/components/agents/MachineField";
import { RunnerSetup } from "@/components/agents/RunnerSetup";
import { ToolsTab } from "@/components/hub/ToolsTab";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { TabPanel, Tabs, useTabParam } from "@/components/ui/Tabs";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { hubKeys, useHubSummary } from "@/lib/hub";
import { qk } from "@/lib/queries";
import type { AccessToken, Agent, Project } from "@/lib/types";
import { usePageTitle } from "@/lib/title";

const TAB_IDS = ["agents", "tools", "runner"] as const;
type Tab = (typeof TAB_IDS)[number];

function MyAgents() {
  const client = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const [tab, setTab] = useTabParam<Tab>(TAB_IDS);
  const [adding, setAdding] = useState(false);
  const agents = useQuery({ queryKey: qk.agents(), queryFn: () => api<Agent[]>("/api/agents/mine") });
  const projects = useQuery({ queryKey: qk.projects(), queryFn: () => api<Project[]>("/api/projects") });
  const tokens = useQuery({ queryKey: qk.tokens(), queryFn: () => api<AccessToken[]>("/api/tokens") });
  const summary = useHubSummary();
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: qk.agents() }),
      client.invalidateQueries({ queryKey: qk.tokens() }), // tokens list their linked agents
      client.invalidateQueries({ queryKey: hubKeys.machines() }), // machines list their agents
    ]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="My agents"
        subtitle="Register the coding agents on your computer and tell each one where a project's repository lives."
        actions={<Button onClick={() => setAdding(true)}>Add agent</Button>}
      />
      <Tabs
        label="My agents"
        tabs={[
          { id: "agents", label: "Agents" },
          { id: "tools", label: "Tools", mark: !!summary.data?.out_of_step, markLabel: "machines out of step" },
          { id: "runner", label: "Runner" },
        ]}
        value={tab}
        onChange={setTab}
      />
      <TabPanel id="agents" active={tab === "agents"}>
        {agents.error && <p role="alert" className="text-sm text-pink">{errorMessage(agents.error)}</p>}
        {agents.data && (
          <AgentsTab
            agents={agents.data}
            projects={projects.data ?? []}
            tokens={tokens.data ?? []}
            hasMachines={usableRunnerTokens(tokens.data ?? []).length > 0}
            onChanged={refresh}
          />
        )}
      </TabPanel>
      <TabPanel id="tools" active={tab === "tools"}>
        <ToolsTab />
      </TabPanel>
      <TabPanel id="runner" active={tab === "runner"}>
        <section aria-labelledby="runner-heading" className="card space-y-3 p-4">
          <h2 id="runner-heading" className="text-sm font-bold text-cyan-ink">Runner</h2>
          <RunnerSetup hasAgents={(agents.data?.length ?? 0) > 0} />
        </section>
      </TabPanel>
      {adding && (
        <AddAgentDialog
          tokens={tokens.data ?? []}
          onClose={() => setAdding(false)}
          onCreated={async (agent) => {
            setAdding(false);
            router.push(`${pathname}?tab=agents&agent=${agent.id}`, { scroll: false });
            await refresh();
          }}
        />
      )}
    </div>
  );
}

export default function AgentsPage() {
  usePageTitle("My agents");
  return (
    <Suspense>
      <MyAgents />
    </Suspense>
  );
}
