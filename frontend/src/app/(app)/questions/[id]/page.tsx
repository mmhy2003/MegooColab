"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { QuestionView } from "@/components/questions/QuestionView";
import { errorMessage } from "@/lib/errors";
import { useQuestion } from "@/lib/questions";
import { usePageTitle } from "@/lib/title";

export default function QuestionPage() {
  const { id } = useParams<{ id: string }>();
  const question = useQuestion(id);
  usePageTitle(question.data && `${question.data.ref} ${question.data.title}`, "Questions");

  if (question.error) {
    return (
      <div className="card mx-auto mt-10 max-w-md p-6 text-center">
        <p className="text-pink">{errorMessage(question.error)}</p>
        <Link href="/questions">Back to Questions</Link>
      </div>
    );
  }
  if (!question.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  return (
    <div className="space-y-4">
      <p className="text-sm">
        <Link href="/questions">Questions</Link>
      </p>
      <QuestionView question={question.data} />
    </div>
  );
}
