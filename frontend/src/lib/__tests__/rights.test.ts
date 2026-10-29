import { describe, expect, it } from "vitest";

import { canDeleteTask, projectRights, teamChoices } from "@/lib/rights";
import type { User } from "@/lib/types";

const user = (role: string, id = "u1") => ({ id, role }) as unknown as User;
const project = (status: string) => ({ status }) as never;

describe("projectRights", () => {
  it("an active project: writing for all but viewers, managing for admins and managers", () => {
    expect(projectRights(user("admin"), project("active"))).toEqual({
      canWrite: true, canManage: true, canChangeStatus: true, canDeleteProject: true, closed: false,
    });
    expect(projectRights(user("manager"), project("active"))).toEqual({
      canWrite: true, canManage: true, canChangeStatus: true, canDeleteProject: false, closed: false,
    });
    expect(projectRights(user("member"), project("active"))).toEqual({
      canWrite: true, canManage: false, canChangeStatus: false, canDeleteProject: false, closed: false,
    });
    expect(projectRights(user("viewer"), project("active"))).toEqual({
      canWrite: false, canManage: false, canChangeStatus: false, canDeleteProject: false, closed: false,
    });
  });

  it("a closed project is read-only; managers can still reopen it and admins delete it", () => {
    for (const status of ["finished", "archived"]) {
      expect(projectRights(user("manager"), project(status))).toEqual({
        canWrite: false, canManage: false, canChangeStatus: true, canDeleteProject: false, closed: true,
      });
      expect(projectRights(user("admin"), project(status))).toEqual({
        canWrite: false, canManage: false, canChangeStatus: true, canDeleteProject: true, closed: true,
      });
      expect(projectRights(user("member"), project(status)).canWrite).toBe(false);
    }
  });

  it("nothing while the user or the project is still loading", () => {
    const none = { canWrite: false, canManage: false, canChangeStatus: false, canDeleteProject: false, closed: false };
    expect(projectRights(undefined, project("active"))).toEqual(none);
    expect(projectRights(user("admin"), undefined)).toEqual(none);
  });
});

describe("canDeleteTask", () => {
  const active = (role: string) => projectRights(user(role), project("active"));
  it("the reporter, a manager or an admin, in an open project", () => {
    expect(canDeleteTask(user("member"), { reporter_id: "u1" }, active("member"))).toBe(true);
    expect(canDeleteTask(user("member"), { reporter_id: "u2" }, active("member"))).toBe(false);
    expect(canDeleteTask(user("manager"), { reporter_id: "u2" }, active("manager"))).toBe(true);
    expect(canDeleteTask(user("admin"), { reporter_id: null }, active("admin"))).toBe(true);
    const closed = projectRights(user("member"), project("archived"));
    expect(canDeleteTask(user("member"), { reporter_id: "u1" }, closed)).toBe(false);
  });
});

describe("teamChoices", () => {
  const teams = [
    { id: "a", name: "A", is_member: true },
    { id: "b", name: "B", is_member: false },
    { id: "c", name: "C", is_member: false },
  ] as never[];
  const ids = (list: { id: string }[]) => list.map((t) => t.id);

  it("admins may attach any team, others only their own", () => {
    expect(ids(teamChoices(teams, user("admin"), []))).toEqual(["a", "b", "c"]);
    expect(ids(teamChoices(teams, user("manager"), []))).toEqual(["a"]);
  });

  it("keeps a project's current teams listed, so saving does not drop them", () => {
    expect(ids(teamChoices(teams, user("manager"), ["c"]))).toEqual(["a", "c"]);
  });
});
