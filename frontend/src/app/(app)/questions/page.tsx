"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { AskQuestion } from "@/components/questions/AskQuestion";
import { QuestionList } from "@/components/questions/QuestionList";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { useProjects } from "@/lib/project";
import { QUESTION_STATUSES, useQuestions } from "@/lib/questions";

type Tab = "ask" | "mine" | "incoming";
const TABS: { value: Tab; label: string }[] = [
  { value: "ask", label: "Ask" },
  { value: "mine", label: "My questions" },
  { value: "incoming", label: "Incoming" },
];

function Incoming() {
  const projects = useProjects();
  const [project, setProject] = useState("");
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
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("ask");
  return (
    <div className="space-y-6">
      <PageHeader
        title="Questions"
        subtitle="Ask another project about its code. An agent of that project reads the code and answers, citing files; the answer is filed in its Knowledge Base."
      />
      <div role="tablist" aria-label="Questions" className="flex gap-2 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            role="tab"
            aria-selected={tab === t.value}
            className={`px-3 py-1 text-sm ${tab === t.value ? "border-b-2 border-cyan text-cyan-ink" : "text-muted"}`}
            onClick={() => setTab(t.value)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "ask" && <AskQuestion onAsked={(id) => router.push(`/questions/${id}`)} />}
      {tab === "mine" && <Mine />}
      {tab === "incoming" && <Incoming />}
    </div>
  );
}
