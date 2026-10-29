# Role-aware Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Screens offer only the actions the person may take: hidden when never theirs, read-only in closed projects, disabled with a reason when blocked by state.

**Architecture:** One frontend helper, `projectRights(me, project)`, decides a person's rights in a project from their role and the project's status; the board, backlog, task page and project settings use it instead of their scattered "not a viewer" checks. Two small API additions cover what the frontend cannot know (team membership in the team list, a team's true project count).

**Tech Stack:** Next 16 / React 19 / TanStack Query / vitest (frontend); FastAPI + pytest (backend, two schema fields).

**Spec:** `docs/superpowers/specs/2026-10-29-role-aware-actions-design.md`

## Global Constraints

- No server permission check changes; the server stays the authority.
- Never-yours actions are hidden (or read-only forms); closed projects are read-only like a viewer's view; state-blocked actions are disabled with the reason.
- Copy, verbatim: team delete reason `Move or delete this team's projects first.`; admin guard `You don't have permission to do that.` (the existing card used by the AI and Git pages).
- Never two pytest runs at once. Commit trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A manager in an archived project: no Add/Delete/Save anywhere in the project except the Status switch (Task 2 `TaskView` closed test, Task 3 settings closed test).
2. A member who reported a task can delete it; a member who did not cannot see Delete (Task 1 `canDeleteTask` test, Task 2 test).
3. An admin sees every team in the checkboxes even without membership (Task 4 test).
4. A project's existing team the manager does not belong to stays listed and checked, so saving does not silently drop it (Task 4 test).
5. A viewer's card cannot be picked up by drag or keyboard (Task 2 `TaskCard` test).

---

### Task 1: The rights helper

**Files:**
- Create: `frontend/src/lib/rights.ts`
- Test: `frontend/src/lib/__tests__/rights.test.ts`

**Interfaces:**
- Produces:
  - `type ProjectRights = { canWrite: boolean; canManage: boolean; canChangeStatus: boolean; canDeleteProject: boolean; closed: boolean }`
  - `projectRights(me: User | undefined, project: Pick<Project, "status"> | undefined): ProjectRights` — `closed` = status is not `active`; `canWrite` = me set, role ≠ viewer, not closed; `canManage` = `canManage(me)` (from `lib/me`) and not closed; `canChangeStatus` = `canManage(me)`; `canDeleteProject` = role admin. Everything false while `me` or `project` is undefined.
  - `canDeleteTask(me: User | undefined, task: Pick<Task, "reporter_id">, rights: ProjectRights): boolean` — `rights.canWrite && (task.reporter_id === me?.id || rights.canManage)`.

- [ ] **Step 1: Write the failing tests** — `projectRights` table: admin/manager/member/viewer × active/finished/archived, asserting the five flags (e.g. manager+archived → `{canWrite:false, canManage:false, canChangeStatus:true, canDeleteProject:false, closed:true}`; member+active → `canWrite:true, canManage:false`); undefined me or project → all false. `canDeleteTask`: reporter member → true; other member → false; manager → true; reporter in a closed project → false.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/lib/__tests__/rights.test.ts` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `lib/rights.ts`.
- [ ] **Step 4: Run** the same — Expected: PASS.
- [ ] **Step 5: Commit** `feat(frontend): one helper for a person's rights in a project`.

### Task 2: Board, backlog and task page

**Files:**
- Modify: `frontend/src/app/(app)/projects/[key]/board/page.tsx` (`canWrite`), `frontend/src/app/(app)/projects/[key]/backlog/page.tsx` (`disabled`, `canPlan`), `frontend/src/components/task/TaskView.tsx` (`disabled`, Delete task), `frontend/src/components/board/TaskCard.tsx` (`useSortable`), `frontend/src/components/board/Board.tsx` / `Column.tsx` (pass `canWrite` to cards)
- Test: `frontend/src/components/task/__tests__/rights.test.tsx`, `frontend/src/components/board/__tests__/TaskCard.test.tsx`

**Interfaces:**
- Consumes: Task 1 `projectRights`, `canDeleteTask`.
- Produces: `TaskCard` prop `canDrag: boolean` (passed as `useSortable({ disabled: !canDrag })`).

- [ ] **Step 1: Write the failing tests**
  - `TaskView` in an archived project as a manager (fetch mocks for `/api/auth/me`, `/api/projects/PAY` with `status: "archived"`, the task): no "Delete task" button, the title and fields are disabled, no comment box.
  - `TaskView` in an active project as a member who is not the reporter: no "Delete task"; as the reporter: "Delete task" shown.
  - `TaskCard` with `canDrag={false}`: the card has no `aria-roledescription="sortable"` drag handle attributes (dnd-kit's `attributes` are not applied as draggable — assert `aria-disabled="true"` on the sortable element).
- [ ] **Step 2: Run** `npx vitest run src/components/task/__tests__/rights.test.tsx src/components/board/__tests__/TaskCard.test.tsx` — Expected: FAIL.
- [ ] **Step 3: Implement.** Board: `canWrite = projectRights(me, project.data).canWrite`, passed down to `TaskCard` as `canDrag`. Backlog: `disabled = !rights.canWrite`, `canPlan = rights.canManage`. TaskView: `disabled = !rights.canWrite` (the drawer already threads `disabled` into fields, comments, attachments, links, subtasks, WorkflowPanel, DocumentView, MockupPanel, questions); Delete task shown when `canDeleteTask(me, t, rights)`.
- [ ] **Step 4: Run** `npx vitest run` — Expected: PASS (existing board/backlog/task tests may need `status: "active"` in their project fixtures; add it there).
- [ ] **Step 5: Commit** `feat(frontend): closed projects are read-only; delete and drag follow the rules`.

### Task 3: Project settings

**Files:**
- Modify: `frontend/src/app/(app)/projects/[key]/settings/page.tsx` (`General`, editor props), `frontend/src/components/project/ColumnEditor.tsx`, `RepoEditor.tsx`, `LabelEditor.tsx`
- Test: `frontend/src/app/(app)/projects/[key]/settings/__tests__/rights.test.tsx`

**Interfaces:**
- Consumes: Task 1 `projectRights`.
- Produces: `canEdit: boolean` prop on `General`, `ColumnEditor`, `RepoEditor`, `LabelEditor` (as `WorkflowSettings` already has).

- [ ] **Step 1: Write the failing tests**
  - A member opens settings: General shows the name and description as text (no Save button, no inputs); Columns, Repositories and Labels list their items with no add/rename/delete/reorder controls; Workflow shows its read-only view.
  - A manager in an archived project: the same read-only views, and the Status switch is still enabled.
  - A manager in an active project: Save, Add column, Add repository, Add label all present.
- [ ] **Step 2: Run** the new test file — Expected: FAIL.
- [ ] **Step 3: Implement.** `canEdit = rights.canManage` for all five sections; `StatusSection canChange = rights.canChangeStatus`; read-only = the same list without its controls.
- [ ] **Step 4: Run** `npx vitest run` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(frontend): project settings are read-only unless you manage the project`.

### Task 4: Teams — own teams in the checkboxes, delete only when empty

**Files:**
- Modify: `backend/app/teams/schemas.py` (`TeamSummary.is_member: bool`, `TeamDetail.project_count: int`), `backend/app/teams/router.py` (list and detail), `frontend/src/lib/api-types.ts` (regenerated), `frontend/src/app/(app)/projects/new/page.tsx`, `frontend/src/app/(app)/projects/[key]/settings/page.tsx` (`General` team checkboxes), `frontend/src/app/(app)/teams/[id]/page.tsx`
- Test: `backend/tests/teams/test_rights_fields.py`, `frontend/src/components/project/__tests__/team-choices.test.tsx` (or beside the pages)

**Interfaces:**
- Produces: `TeamSummary.is_member` (the caller is a member), `TeamDetail.project_count` (all the team's projects, whatever the caller can see); frontend `teamChoices(teams: TeamSummary[], me: User | undefined, current: string[]): TeamSummary[]` in `lib/rights.ts` — admins get all; others get `is_member` teams plus any team id in `current`.

- [ ] **Step 1: Write the failing tests**
  - Backend `test_team_list_says_is_member`: a manager in team A only → `is_member` true for A, false for B. `test_team_detail_counts_all_projects`: a team with two projects, the caller sees one → `project_count == 2` while `projects` lists one.
  - Frontend `teamChoices`: admin → all; manager → own teams; manager with `current` containing a foreign team → that team included.
  - Team page: `project_count: 1` → the Delete button is disabled and `Move or delete this team's projects first.` is shown; `project_count: 0` → enabled.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/teams/test_rights_fields.py -q` and the frontend files — Expected: FAIL.
- [ ] **Step 3: Implement**; `npm run gen:api` after the backend change; use `teamChoices` in both team checkbox lists.
- [ ] **Step 4: Run** `uv run pytest tests/teams -q` and `npx vitest run` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: team checkboxes show your teams; team delete waits for its projects`.

### Task 5: Admin page guards

**Files:**
- Modify: `frontend/src/app/(app)/admin/agents/page.tsx`, `audit/page.tsx`, `settings/page.tsx`, `users/page.tsx`
- Test: `frontend/src/app/(app)/admin/__tests__/guards.test.tsx`

**Interfaces:**
- Consumes: nothing new; the AI page's guard pattern (`if (me.role !== "admin")` → the permission card).

- [ ] **Step 1: Write the failing test** — for each of the four pages, rendered with a `member` from `/api/auth/me`: the text `You don't have permission to do that.` is shown and no admin data request is made (fetch called only for `/api/auth/me`).
- [ ] **Step 2: Run** `npx vitest run "src/app/(app)/admin/__tests__/guards.test.tsx"` — Expected: FAIL.
- [ ] **Step 3: Implement** the guard in each page (render nothing until `me` loads, as the AI page does; the data hooks only run inside the guarded child).
- [ ] **Step 4: Run** `npx vitest run`, `npx tsc --noEmit`, `npm run lint` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(frontend): admin pages guard themselves`.
