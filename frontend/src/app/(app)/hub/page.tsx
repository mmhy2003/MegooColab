"use client";

import Link from "next/link";
import { Suspense, useState } from "react";

import { ToolRow } from "@/components/hub/ToolRow";
import { buttonClass } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { TabPanel, Tabs, useTabParam } from "@/components/ui/Tabs";
import { errorMessage } from "@/lib/errors";
import { useHubShelf, type HubShelf } from "@/lib/hub";
import { usePageTitle } from "@/lib/title";

const SHELVES = [
  { id: "mine", label: "Mine" },
  { id: "shared", label: "Shared with me" },
  { id: "everyone", label: "Everyone" },
] as const;

function Shelf({ shelf, q }: { shelf: HubShelf; q: string }) {
  const tools = useHubShelf(shelf, q);
  if (tools.error) return <p role="alert" className="text-sm text-pink">{errorMessage(tools.error)}</p>;
  if (!tools.data) return null;
  if (tools.data.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">{shelf === "mine" ? "Nothing here yet." : "Nothing shared with you yet."}</p>
    );
  }
  return (
    <ul className="space-y-2">
      {tools.data.map((t) => (
        <ToolRow key={t.id} tool={t} mine={shelf === "mine"} />
      ))}
    </ul>
  );
}

function Hub() {
  usePageTitle("Tool Hub");
  const [shelf, setShelf] = useTabParam<HubShelf>(SHELVES.map((s) => s.id));
  const [q, setQ] = useState("");
  return (
    <div className="max-w-4xl">
      <PageHeader
        title="Tool Hub"
        subtitle="MCP servers and skills you keep once and push to your machines. Keys stay with you; sharing never sends them."
        actions={
          <>
            <Link href="/hub/new-skill" className={buttonClass("ghost")}>Add skill</Link>
            <Link href="/hub/new-mcp" className={buttonClass("primary")}>Add MCP</Link>
          </>
        }
      />
      <Tabs label="Shelves" tabs={SHELVES} value={shelf} onChange={setShelf} />
      <input
        type="search"
        aria-label="Search tools"
        placeholder="Search tools…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        maxLength={200}
        className="mb-3 w-full rounded border border-line bg-surface-2 px-2 py-1.5 text-sm text-fg placeholder:text-muted-foreground focus:border-cyan focus:outline-none"
      />
      {SHELVES.map((s) => (
        <TabPanel key={s.id} id={s.id} active={shelf === s.id}>
          {shelf === s.id && <Shelf shelf={s.id} q={q.trim()} />}
        </TabPanel>
      ))}
    </div>
  );
}

export default function HubPage() {
  return (
    <Suspense>
      <Hub />
    </Suspense>
  );
}
