"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/queries";
import type { Column, Label, Project, Repo, Sprint, Task, Team, User } from "@/lib/types";

export function useProjects() {
  return useQuery({ queryKey: qk.projects(), queryFn: () => api<Project[]>("/api/projects") });
}

export function useProject(key: string) {
  return useQuery({ queryKey: qk.project(key), queryFn: () => api<Project>(`/api/projects/${key}`) });
}

export function useColumns(key: string) {
  return useQuery({ queryKey: qk.columns(key), queryFn: () => api<Column[]>(`/api/projects/${key}/columns`) });
}

export function useLabels(key: string) {
  return useQuery({ queryKey: qk.labels(key), queryFn: () => api<Label[]>(`/api/projects/${key}/labels`) });
}

export function useRepos(key: string) {
  return useQuery({ queryKey: qk.repositories(key), queryFn: () => api<Repo[]>(`/api/projects/${key}/repositories`) });
}

export function useTeams() {
  return useQuery({ queryKey: qk.teams(), queryFn: () => api<Team[]>("/api/teams") });
}

export function useUsers() {
  return useQuery({ queryKey: qk.users(), queryFn: () => api<User[]>("/api/users") });
}

export function useTasks(key: string, filters: Record<string, string | undefined> = {}) {
  const params = new URLSearchParams(
    Object.entries(filters).filter((e): e is [string, string] => Boolean(e[1])),
  ).toString();
  return useQuery({
    queryKey: qk.tasks(key, filters),
    queryFn: () => api<Task[]>(`/api/projects/${key}/tasks${params ? `?${params}` : ""}`),
  });
}

export function useSprints(key: string, enabled = true) {
  return useQuery({
    queryKey: qk.sprints(key),
    queryFn: () => api<Sprint[]>(`/api/projects/${key}/sprints`),
    enabled,
  });
}
