"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type KbDraft = S["DraftOut"];
export type KbDraftSummary = S["DraftSummary"];
export type DraftAgent = S["DraftAgentOut"];
export type DraftSegment = S["Segment"];
export type DraftMessage = S["DraftMessageOut"];
export type DraftTarget = S["DraftTarget"];

/** Every draft query starts with "kb-drafts", so one live event (kb_draft.updated) refreshes them all. */
export const kbDraftKeys = {
  all: ["kb-drafts"] as const,
  list: () => ["kb-drafts", "list"] as const,
  one: (id: string) => ["kb-drafts", id] as const,
  agents: (spaceId: string) => ["kb-drafts", "agents", spaceId] as const,
};

export function useKbDrafts() {
  return useQuery({ queryKey: kbDraftKeys.list(), queryFn: () => api<KbDraftSummary[]>("/api/kb/drafts") });
}

export function useKbDraft(id: string) {
  return useQuery({ queryKey: kbDraftKeys.one(id), queryFn: () => api<KbDraft>(`/api/kb/drafts/${id}`) });
}

export function useDraftAgents(spaceId: string, enabled = true) {
  return useQuery({
    queryKey: kbDraftKeys.agents(spaceId),
    queryFn: () => api<DraftAgent[]>(`/api/kb/drafts/agents?space_id=${spaceId}`),
    enabled,
  });
}

export const draftTitle = (title: string) => title.trim() || "Untitled draft";
