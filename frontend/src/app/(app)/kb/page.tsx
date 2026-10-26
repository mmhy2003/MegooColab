"use client";

import { Building2, FolderKanban, Search, UsersRound } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { SPACE_GROUPS, useKbSpaces } from "@/lib/kb";

const ICONS = { org: Building2, team: UsersRound, project: FolderKanban };

export default function KnowledgeBasePage() {
  const spaces = useKbSpaces();
  const router = useRouter();
  const [q, setQ] = useState("");
  return (
    <div>
      <PageHeader title="Knowledge Base" subtitle="Shared documents for people and agents: designs, plans, guides and notes." />
      <form
        role="search"
        className="mb-6 flex max-w-xl gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (q.trim()) router.push(`/kb/search?q=${encodeURIComponent(q.trim())}`);
        }}
      >
        <input
          aria-label="Search the Knowledge Base"
          className="w-full rounded border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder:text-muted focus:border-cyan focus:outline-none"
          placeholder="Search the Knowledge Base…"
          maxLength={500}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Button type="submit">
          <Search size={14} aria-hidden /> Search
        </Button>
      </form>
      {SPACE_GROUPS.map(({ kind, label }) => {
        const group = (spaces.data ?? []).filter((s) => s.kind === kind);
        if (group.length === 0) return null;
        const Icon = ICONS[kind];
        return (
          <section key={kind} className="mb-6">
            <h2 className="mb-2 text-xs tracking-widest text-muted uppercase">{label}</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {group.map((s) => (
                <Link key={s.id} href={`/kb/${s.id}`} className="card flex items-center gap-2 p-4 text-fg no-underline hover:glow-box">
                  <Icon size={16} aria-hidden className="shrink-0 text-cyan-ink" />
                  <span className="truncate text-sm">{s.name}</span>
                  {!s.can_write && <span className="ml-auto text-xs text-muted">read only</span>}
                </Link>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
