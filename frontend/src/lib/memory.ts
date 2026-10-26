"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type MemEntity = S["MemEntityOut"];
export type MemEntityDetail = S["MemEntityDetail"];
export type MemConclusion = S["ConclusionOut"];
export type MemConclusionPage = S["ConclusionPage"];
export type MemConclusionDetail = S["ConclusionDetail"];
export type MemChainNode = S["ChainNode"];
export type MemAnswer = S["AskOut"];
export type MemDreamRun = S["DreamRunOut"];
export type ConclusionStatusFilter = "active" | "superseded" | "deleted";

/** Every memory query starts with "mem", so one invalidation refreshes them all. */
export const memKeys = {
  all: ["mem"] as const,
  entities: (kind: string, q: string) => ["mem", "entities", kind, q] as const,
  entity: (id: string) => ["mem", "entity", id] as const,
  conclusions: (entityId: string, status: string) => ["mem", "conclusions", entityId, status] as const,
  conclusion: (id: string) => ["mem", "conclusion", id] as const,
  dreams: () => ["mem", "dreams"] as const,
};

export function useMemEntities(kind = "", q = "") {
  const params = new URLSearchParams();
  if (kind) params.set("kind", kind);
  if (q) params.set("q", q);
  const query = params.toString();
  return useQuery({
    queryKey: memKeys.entities(kind, q),
    queryFn: () => api<MemEntity[]>(`/api/memory/entities${query ? `?${query}` : ""}`),
  });
}

export function useMemEntity(id: string) {
  return useQuery({ queryKey: memKeys.entity(id), queryFn: () => api<MemEntityDetail>(`/api/memory/entities/${id}`) });
}

export function useMemConclusions(entityId: string, status: ConclusionStatusFilter) {
  return useInfiniteQuery({
    queryKey: memKeys.conclusions(entityId, status),
    initialPageParam: "",
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ status, limit: "50" });
      if (pageParam) params.set("cursor", pageParam);
      return api<MemConclusionPage>(`/api/memory/entities/${entityId}/conclusions?${params}`);
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

export function useMemConclusion(id: string, enabled = true) {
  return useQuery({
    queryKey: memKeys.conclusion(id),
    queryFn: () => api<MemConclusionDetail>(`/api/memory/conclusions/${id}`),
    enabled,
  });
}

export const ENTITY_GROUPS: { kind: MemEntity["kind"]; label: string }[] = [
  { kind: "org", label: "Organization" },
  { kind: "team", label: "Teams" },
  { kind: "project", label: "Projects" },
  { kind: "product", label: "Products" },
  { kind: "user", label: "People" },
  { kind: "agent", label: "Agents" },
];

export function kindLabel(c: Pick<MemConclusion, "kind" | "confidence">): string {
  return c.kind === "induced" && c.confidence !== null ? `induced · ${Math.round(c.confidence * 100)}%` : c.kind;
}
