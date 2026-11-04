"use client";

import { useParams } from "next/navigation";

import { DraftPage } from "@/components/kb/drafts/DraftPage";

export default function KbDraftPage() {
  const { draftId } = useParams<{ draftId: string }>();
  return <DraftPage draftId={draftId} />;
}
