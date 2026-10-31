"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AskQuestion } from "@/components/questions/AskQuestion";
import { QuestionList } from "@/components/questions/QuestionList";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { useMe } from "@/lib/me";
import { useProjects } from "@/lib/project";
import { QUESTION_STATUSES, useQuestions } from "@/lib/questions";
import { usePageTitle } from "@/lib/title";

type Tab = "ask" | "mine" | "incoming";
const TABS: { value: Tab; label: string }[] = [
  { value: "ask", label: "Ask" },
  { value: "mine", label: "My questions" },
  { value: "incoming", label: "Incoming" },
];

function Incoming({ initialProject = "" }: { initialProject?: string }) {
  const projects = useProjects();
  const [project, setProject] = useState(initialProject);
  const [status, setStatus] = useState("");
  const questions = useQuestions("incoming", project, status);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Select label="Project" value={project} onChange={(e) => setProject(e.target.value)}>
          <option value="">All my projects</option>
          {(projects.data ?? []).map((p) => (
            <option key={p.id} value={p.key}>
              {p.key} — {p.name}
            </option>
          ))}
        </Select>
        <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any</option>
          {QUESTION_STATUSES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </Select>
      </div>
      {questions.data && <QuestionList questions={questions.data} empty="No questions to your projects." />}
    </div>
  );
}

function Mine() {
  const questions = useQuestions("mine");
  return questions.data ? <QuestionList questions={questions.data} empty="You haven't asked anything yet." /> : null;
}

export default function QuestionsPage() {
  usePageTitle("Questions");
  return (
    <Suspense>
      <Questions />
    </Suspense>
  );
}

/** `?tab=incoming&project=PAY` opens a tab (the project header links here). Viewers cannot ask. */
function Questions() {
  const router = useRouter();
  const params = useSearchParams();
  const { data: me } = useMe();
  const canAsk = me?.role !== "viewer";
  const tabs = canAsk ? TABS : TABS.filter((t) => t.value !== "ask");
  const linked = tabs.find((t) => t.value === params.get("tab"))?.value;
  const [chosen, setTab] = useState<Tab | null>(null);
  const tab = chosen && tabs.some((t) => t.value === chosen) ? chosen : (linked ?? tabs[0].value);
  return (
    <div className="space-y-6">
      <PageHeader
        title="Questions"
        subtitle="Ask another project about its code. An agent of that project reads the code and answers, citing files; the answer is filed in its Knowledge Base."
      />
      <div role="tablist" aria-label="Questions" className="flex gap-2 border-b border-line">
        {tabs.map((t) => (
          <button
            key={t.value}
            type="button"
            role="tab"
            aria-selected={tab === t.value}
            className={`px-3 py-1 text-sm ${tab === t.value ? "border-b-2 border-cyan text-cyan-ink" : "text-muted-foreground"}`}
            onClick={() => setTab(t.value)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "ask" && <AskQuestion onAsked={(id) => router.push(`/questions/${id}`)} />}
      {tab === "mine" && <Mine />}
      {tab === "incoming" && <Incoming initialProject={params.get("project") ?? ""} />}
    </div>
  );
}
