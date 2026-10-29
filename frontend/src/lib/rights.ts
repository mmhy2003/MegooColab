import { canManage as isManagerOrAdmin } from "@/lib/me";
import type { Project, Task, Team, User } from "@/lib/types";

/** What a person may do in a project: the server's rules, so screens offer only those actions. The server still
 *  checks every request. People only see projects through their own teams, so a manager who can see a project
 *  manages it. A finished or archived project is read-only; its managers can still reopen it. */
export type ProjectRights = {
  canWrite: boolean;
  canManage: boolean;
  canChangeStatus: boolean;
  canDeleteProject: boolean;
  closed: boolean;
};

const NONE: ProjectRights = { canWrite: false, canManage: false, canChangeStatus: false, canDeleteProject: false, closed: false };

export function projectRights(me: User | undefined, project: Pick<Project, "status"> | undefined): ProjectRights {
  if (!me || !project) return NONE;
  const closed = project.status !== "active";
  const manager = isManagerOrAdmin(me);
  return {
    canWrite: me.role !== "viewer" && !closed,
    canManage: manager && !closed,
    canChangeStatus: manager,
    canDeleteProject: me.role === "admin",
    closed,
  };
}

/** The task's reporter, a project manager or an admin, while the project is open. */
export function canDeleteTask(me: User | undefined, task: Pick<Task, "reporter_id">, rights: ProjectRights): boolean {
  return rights.canWrite && ((!!me && task.reporter_id === me.id) || rights.canManage);
}

/** The teams a person may attach to a project: any for an admin, otherwise their own. A project's current teams
 *  stay listed (checked), so saving the form never drops a team the person could not have added. */
export function teamChoices<T extends Pick<Team, "id" | "is_member">>(teams: T[], me: User | undefined, current: string[]): T[] {
  if (me?.role === "admin") return teams;
  return teams.filter((t) => t.is_member || current.includes(t.id));
}
