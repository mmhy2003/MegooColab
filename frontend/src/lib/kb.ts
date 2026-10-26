"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type KbSpace = S["SpaceOut"];
export type KbSpaceRef = S["SpaceRef"];
export type KbFolder = S["FolderOut"];
export type KbTreeDoc = S["TreeDoc"];
export type KbTree = S["TreeOut"];
export type KbDocument = S["KbDocumentOut"];
export type KbRevisionSummary = S["RevisionSummary"];
export type KbRevision = S["RevisionOut"];
export type KbDocRef = S["DocRef"];
export type KbSearchResult = S["SearchOut"];
export type KbSearchHit = S["SearchHit"];
export type KbResolved = S["Resolved"];

export type DiffOp =
  | { op: "equal" | "insert" | "delete" | "replace"; a_start: number; b_start: number; a_lines: string[]; b_lines: string[] }
  | { op: "collapsed"; count: number };

/** Every Knowledge Base query starts with "kb", so one live event refreshes them all. */
export const kbKeys = {
  all: ["kb"] as const,
  spaces: () => ["kb", "spaces"] as const,
  tree: (spaceId: string) => ["kb", "tree", spaceId] as const,
  doc: (id: string) => ["kb", "doc", id] as const,
  revisions: (id: string) => ["kb", "revisions", id] as const,
  revision: (id: string, n: number) => ["kb", "revision", id, n] as const,
  diff: (id: string, a: number, b: number) => ["kb", "diff", id, a, b] as const,
  backlinks: (id: string) => ["kb", "backlinks", id] as const,
  refs: (taskKey: string) => ["kb", "refs", taskKey] as const,
  search: (q: string, space: string) => ["kb", "search", q, space] as const,
  resolve: (ids: string[]) => ["kb", "resolve", ...ids] as const,
};

export function useKbSpaces() {
  return useQuery({ queryKey: kbKeys.spaces(), queryFn: () => api<KbSpace[]>("/api/kb/spaces") });
}

export function useKbTree(spaceId: string) {
  return useQuery({ queryKey: kbKeys.tree(spaceId), queryFn: () => api<KbTree>(`/api/kb/spaces/${spaceId}/tree`) });
}

export function useKbDocument(id: string) {
  return useQuery({ queryKey: kbKeys.doc(id), queryFn: () => api<KbDocument>(`/api/kb/documents/${id}`) });
}

export function useKbRevisions(id: string) {
  return useQuery({
    queryKey: kbKeys.revisions(id),
    queryFn: () => api<KbRevisionSummary[]>(`/api/kb/documents/${id}/revisions`),
  });
}

export function useKbSearch(q: string, space: string) {
  const params = new URLSearchParams({ q });
  if (space) params.set("space", space);
  return useQuery({
    queryKey: kbKeys.search(q, space),
    queryFn: () => api<KbSearchResult>(`/api/kb/search?${params}`),
    enabled: q.trim().length > 0,
  });
}

/** "folder/sub/Title", or just the title at a space's root. */
export function kbPath(doc: { path: string; title: string }): string {
  return doc.path ? `${doc.path}/${doc.title}` : doc.title;
}

export const SPACE_GROUPS: { kind: KbSpace["kind"]; label: string }[] = [
  { kind: "org", label: "Organization" },
  { kind: "team", label: "Teams" },
  { kind: "project", label: "Projects" },
];
