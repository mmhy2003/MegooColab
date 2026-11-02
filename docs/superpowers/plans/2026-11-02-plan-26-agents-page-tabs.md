# My agents page: tabs, list and side panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settings › My agents becomes three tabs (Agents, Tools, Runner), each a short list with the chosen item's
details beside it (full screen with Back on a phone), with a compact project list and a guided "Add a machine".

**Architecture:** One shared `ListDetail` layout plus a `useChosenParam` hook (chosen item in the address) serve all
three tabs. The page becomes a thin shell over `AgentsTab`, `ToolsTab` and `RunnerTab`. Bindings are edited one at a
time through the existing whole-list PUT. The only backend change is `runner_version` on `HubMachineOut`.

**Tech Stack:** Next.js (app router) + React Query + Tailwind, Vitest + Testing Library, FastAPI, Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-11-02-agents-page-design.md`

## Global Constraints

- Tabs `?tab=agents|tools|runner` via the existing `useTabParam`/`Tabs` (`frontend/src/components/ui/Tabs.tsx`);
  Agents is the default; the page content is wrapped in `<Suspense>`.
- Chosen item in the address: `agent=<id>` (Agents), `machine=<token id>` (Tools and Runner share it),
  `machine=new` = Add a machine. Unknown ids are ignored: desktop shows the first item, a phone shows the list.
- Split at Tailwind `md`: below it, list alone or details alone under a "‹ Agents" / "‹ Tools" / "‹ Runner" back link.
- Projects: 10 lines (sorted by project key) then "Show N more"; a search shows every match.
- Remove-binding confirm, verbatim: title `Remove <KEY> from <agent name>?`, text `The agent stops working on it.`,
  button `Remove`.
- Folder validation and its message stay as today (`isAbsolutePath`; "Enter the full path to the repository, such as
  C:\code\payments or /home/me/code/payments.").
- Add a machine tokens: `POST /api/tokens` `{name, scopes: ["runner"], expires_in_days: null}`.
- Never-connected copy, verbatim: "This machine hasn't connected yet. Its token was shown once when you made it; if
  you no longer have it, set the machine up again with Add a machine and revoke this one under Access tokens."
- No other backend change; no runner change; no new npm dependency (the ⋯ menu uses
  `frontend/src/components/shadcn/dropdown-menu.tsx`).
- Machine OS values are `windows`, `linux`, `macos` (`OS_LABEL` in `frontend/src/lib/hub.ts`).
- No Prettier (≈120-column lines, match surrounding code). Work on branch `feat/agents-page-tabs` off develop. Every
  commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Test commands: backend `cd backend && uv run pytest <files> -q` (never two pytest runs at once); web
  `cd frontend && npx vitest run <files>`, then `npx tsc --noEmit -p . && npx eslint <changed files>`.

## Review Focus

1. Many projects (40+) and a long Windows folder on a 375px phone: one line per project, the folder cut with an
   ellipsis, no sideways scroll — pinned by `mobile.spec.ts` (Task 7) with an agent bound to a long path.
2. Two quick binding edits: the second must not drop the first — pinned in Task 4 by
   `disables the list while a save is in flight`.
3. The agent in the address is deleted (or a stale link): the page must not show an empty panel — pinned in Task 2
   (`an unknown id shows the first item and keeps the list on a phone`) and Task 3 (`deleting the chosen agent shows
   the next one`).
4. A just-made token whose runner never connects, then a reload: the machine shows the never-connected copy, not
   empty commands — pinned in Task 6 by `a machine that never connected says how to start over`.
5. Switching tabs keeps a stale `machine=new`: the Tools tab must not choke on it — pinned in Task 5 by
   `machine=new shows the first machine`.

---

### Task 1: Runner version per machine (backend)

**Files:**
- Modify: `backend/app/hub/schemas.py` (`HubMachineOut`), `backend/app/hub/machines.py` (`HubMachineOut(...)` at the
  end of the machine builder, ~line 335)
- Modify: `frontend/src/lib/api-types.ts` (regenerated)
- Test: `backend/tests/hub/test_machines.py`

**Interfaces:**
- Produces: `HubMachineOut.runner_version: str | None` (the connection's `version` from its hello; None while
  offline) → web type `HubMachine["runner_version"]`.

- [ ] **Step 1: Write the failing test** `test_machine_reports_runner_version` in `test_machines.py`, using the
  existing `_me`, `_machine`, `conns` and `_machines` helpers:

```python
async def test_machine_reports_runner_version(client, db, conns):
    user = await _me(client, db)
    token_id = await _machine(client, db)
    assert (await _machines(client))[0]["runner_version"] is None
    conns(token_id, user).version = "0.5.0"
    assert (await _machines(client))[0]["runner_version"] == "0.5.0"
```

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/hub/test_machines.py -q -k runner_version` → KeyError.
- [ ] **Step 3: Implement** — add `runner_version: str | None = None` to `HubMachineOut`; set it to
  `conn.version if conn else None` in the builder.
- [ ] **Step 4: Run, expect PASS** — `uv run pytest tests/hub -q` → all passed. Then regenerate the web types:
  `cd frontend && npm run gen:api` (delete the generated `openapi.json` if it is not tracked; check `git status`).
- [ ] **Step 5: Commit** — `feat(hub): machines report their runner's version`

### Task 2: ListDetail layout and the chosen-item hook

**Files:**
- Create: `frontend/src/components/ui/ListDetail.tsx`
- Modify: `frontend/src/components/ui/Dialog.tsx` (new `phoneFull` prop)
- Test: `frontend/src/components/ui/__tests__/ListDetail.test.tsx`, `frontend/src/components/ui/__tests__/Dialog.test.tsx`
  (create if missing)

**Interfaces:**
- Produces:
  - `useChosenParam(key: "agent" | "machine"): [string | null, (id: string | null) => void]` — reads the search param;
    choosing an id uses `router.push` (so a phone's Back returns to the list), `null` uses `router.replace` and removes
    the param; other params (`tab`) are kept.
  - `pickChosen<T>(items: T[], id: string | null, idOf: (t: T) => string): { shown: T | null; chosen: boolean }` —
    `shown` is the matching item or else the first (null when empty); `chosen` is true only when the id matched.
  - `<ListDetail listLabel: string; backLabel: string; chosen: boolean; onBack: () => void; list: ReactNode;
    detail: ReactNode />` — `md` and up: list (≈1/3) and detail side by side; below `md`: the list when `!chosen`,
    otherwise the detail under a button "‹ {backLabel}" calling `onBack`. The list is a `nav`/`ul` with
    `aria-label={listLabel}`.
  - `<ListRow selected: boolean; onClick: () => void; title: ReactNode; meta?: ReactNode; aside?: ReactNode />` — a
    full-width button row, `aria-current="true"` when selected, title on line 1 (ellipsis), meta on line 2 (muted).
  - `Dialog` prop `phoneFull?: boolean` — below `md` the dialog fills the screen (no margin, full height/width, no
    rounded corners); unchanged at `md` and up.

- [ ] **Step 1: Write the failing tests** in `ListDetail.test.tsx` (mock `next/navigation` as in
  `frontend/src/app/(app)/hub/__tests__/HubPage.test.tsx`):
  - `pickChosen: a matching id is shown and chosen` → `{shown: b, chosen: true}`.
  - `an unknown id shows the first item and keeps the list on a phone` → `pickChosen([a,b], "gone", …)` is
    `{shown: a, chosen: false}`; `pickChosen([], "x", …)` is `{shown: null, chosen: false}`.
  - `useChosenParam pushes a chosen id and keeps the tab` → with `?tab=tools`, choosing `"m1"` calls `push` with
    `/settings/agents?tab=tools&machine=m1`; choosing `null` calls `replace` with `/settings/agents?tab=tools`.
  - `ListDetail shows Back only when an item is chosen` → with `chosen` the "‹ Agents" button exists and calls
    `onBack`; without it there is none.
  - `ListRow marks the selected row` → `aria-current="true"`.
  - In `Dialog.test.tsx`: `phoneFull adds the full-screen classes below md` (class list contains `max-md:inset-0`, or
    whichever classes are chosen — assert one stable class).
- [ ] **Step 2: Run, expect FAIL** — `npx vitest run src/components/ui/__tests__/ListDetail.test.tsx src/components/ui/__tests__/Dialog.test.tsx`.
- [ ] **Step 3: Implement** the four exports and the `phoneFull` prop. Visibility is CSS only (`hidden md:block`
  etc.), so no JS media query is needed.
- [ ] **Step 4: Run, expect PASS**, plus `npx tsc --noEmit -p .` and eslint on the files.
- [ ] **Step 5: Commit** — `feat(ui): list and side panel layout, chosen item in the address`

### Task 3: Page shell and the Agents tab (list, details, ⋯ menu)

**Files:**
- Modify: `frontend/src/app/(app)/settings/agents/page.tsx` (shell: header, tabs, Suspense, Add agent)
- Create: `frontend/src/components/agents/AddAgentDialog.tsx` (moved from the page; new `initialMachine` prop;
  `phoneFull`)
- Create: `frontend/src/components/agents/AgentsTab.tsx` (list + `AgentDetails`)
- Create: `frontend/src/components/agents/AgentMenu.tsx` (⋯ menu, Rename and Answer mode dialogs, Delete)
- Test: `frontend/src/app/(app)/settings/agents/__tests__/add.test.tsx` (keep, add `useSearchParams` to the mock),
  `frontend/src/components/agents/__tests__/AgentsTab.test.tsx`

**Interfaces:**
- Consumes: Task 2 (`ListDetail`, `ListRow`, `pickChosen`, `useChosenParam`, `Dialog phoneFull`).
- Produces:
  - `AddAgentDialog({ tokens, initialMachine?: string | null, onClose, onCreated: (agent: Agent) => void })` — the
    POST's response is passed to `onCreated`; the page then chooses that agent (`agent=<id>`, tab Agents).
  - `AgentsTab({ agents: Agent[]; projects: Project[]; tokens: AccessToken[]; hasMachines: boolean; onChanged: () => Promise<unknown> })`.
  - The page passes `openAddAgent(machine?: string)` to `RunnerTab` later (Task 6): Add agent opened with
    `initialMachine`.
  - Details panel: `<section aria-labelledby>` whose `h2` is the agent's name (so e2e can use
    `getByRole("region", { name })`). Header row: name, program `Badge`, `AgentStatusDot`, `runsLabel` text,
    `RunnerUpdateArrow`, `AgentMenu`. Settings: `MachineField`, `ModelField`, `RunsField` in a grid
    (`md:grid-cols-2`, one column on a phone). Under them, the projects: the old `BindingEditor` stays there in this
    task, and Task 4 replaces it.
- Page header: title and subtitle as today; actions = Add agent only (the `#runner` link goes). Tabs: Agents, Tools
  (`mark` = `useHubSummary().data?.out_of_step`; `TabDef.mark` today means "unsaved changes" — add an optional
  `markLabel?: string` to `TabDef` so the Tools dot reads "Tools (machines out of step)" for screen readers), Runner.
  Until Tasks 5–6, Tools renders `<HubMachines/>` and Runner renders `<RunnerSetup/>` as today.
- List row: title = name + `AgentStatusDot`; aside = `runsLabel` when not null; meta = `"<machine name> · N projects"`
  (`"Not linked · N projects"` when no machine; "1 project" singular).
- Empty list: "No agents yet." + Add agent button; when `!hasMachines`, also "Set up the runner on a machine first:"
  with a link to `?tab=runner`.
- ⋯ menu trigger: `aria-label="Actions for <name>"`; items Rename, Answer mode, Delete.
  - Rename dialog: Input "Name" (1–200, prefilled), Save → PATCH `{name}`.
  - Answer mode dialog: Select "Answer mode" Manual/Auto with `ANSWER_MODE_HELP`, Save → PATCH `{answer_mode}`.
  - Delete: today's confirm copy and DELETE; afterwards the `agent` param is cleared.
  - Errors from any of them show in the details panel's alert, as today.

- [ ] **Step 1: Write the failing tests** in `AgentsTab.test.tsx` (fetch stubbed per URL; `next/navigation` mocked
  with a mutable search string):
  - `lists each agent with its machine and project count` → rows "Mo's Claude Code" with meta
    "Workstation · 2 projects", "Mo's Codex" with "Not linked · 0 projects".
  - `shows the first agent when none is chosen, and the chosen one from the address` → region name = first agent;
    with `?agent=a2`, region name = second.
  - `clicking a row chooses it` → `push` called with `?agent=a2`.
  - `renames from the menu` → open "Actions for Mo's Claude Code", Rename, type, Save → PATCH body `{name: "Mo"}`.
  - `changes the answer mode from the menu` → PATCH body `{answer_mode: "auto"}`.
  - `deleting the chosen agent shows the next one` → confirm Delete → DELETE sent, then `replace` without `agent`.
  - `points to the Runner tab when there are no machines` → empty agents + `hasMachines=false` → link to `?tab=runner`.
  - In `add.test.tsx`: `a new agent is chosen once added` → POST returns `{id: "new1", …}` → `push`/`replace` called
    with `agent=new1`.
- [ ] **Step 2: Run, expect FAIL** — `npx vitest run src/components/agents/__tests__/AgentsTab.test.tsx "src/app/(app)/settings/agents/__tests__/add.test.tsx"`.
- [ ] **Step 3: Implement** the shell, `AddAgentDialog`, `AgentsTab`, `AgentMenu`.
- [ ] **Step 4: Run, expect PASS** — the whole web suite `npx vitest run`, then tsc and eslint on changed files.
- [ ] **Step 5: Commit** — `feat(agents): My agents in tabs; agents as a list with a side panel`

### Task 4: Compact project bindings

**Files:**
- Create: `frontend/src/components/agents/ProjectBindings.tsx`
- Delete: `frontend/src/components/agents/BindingEditor.tsx` and its test
- Modify: `frontend/src/components/agents/AgentsTab.tsx` (use it)
- Test: `frontend/src/components/agents/__tests__/ProjectBindings.test.tsx`

**Interfaces:**
- Consumes: `Agent.bindings` (`{project_id, project_key, local_path}`), `Project[]` for names,
  `PUT /api/agents/{id}/bindings` `{bindings: [{project_ref, local_path}]}`.
- Produces: `ProjectBindings({ agent: Agent; projects: Project[]; onSaved: () => Promise<unknown> })`.
- Labels (e2e relies on them): heading "Projects (N)"; search Input label "Search projects"; button "Add project";
  add row: Select "Project" (only projects not yet bound; option text `KEY Name`), Input "Folder", buttons "Add" and
  "Cancel"; per line: text `KEY Name`, the folder (`title` = full folder), buttons `Edit folder of KEY` and
  `Remove KEY`; edit mode: Input "Folder", "Save", "Cancel"; "Show N more"; empty: "Not working on any project yet.".
- Every save: `bindings` = the agent's saved bindings with this one change, `local_path` trimmed; the change is
  validated with `isAbsolutePath` first (no request when it fails). While saving, Add/Edit/Remove/Save are disabled.
  On error the row stays open with what was typed and the error under it (`errorMessage`, so
  `project_not_accessible` keeps its friendly copy). On success the row closes and `onSaved()` refetches.
- Search matches key, name or folder, case-insensitive. A binding whose project is not in `projects` shows its key
  alone.

- [ ] **Step 1: Write the failing tests** (`ProjectBindings.test.tsx`; move the three cases of the deleted
  `BindingEditor.test.tsx` here, adapted):
  - `adds a project in one row and saves at once` → existing PAY binding, add WEB with `/home/me/web` → PUT body
    `{bindings: [{project_ref: "PAY", local_path: "C:\\code\\payments"}, {project_ref: "WEB", local_path: "/home/me/web"}]}`.
  - `rejects a relative path without calling the server` (from the old test).
  - `shows friendly copy for project_not_accessible` (from the old test), and the typed folder is still there.
  - `only offers projects the agent isn't on`.
  - `edits a folder in place` → Edit folder of PAY, change, Save → PUT with the new path for PAY only.
  - `asks before removing` → Remove PAY → alertdialog "Remove PAY from Ann's Codex?" → Remove → PUT without PAY;
    Cancel sends nothing.
  - `shows 10 projects, then the rest on request` → 14 bindings: 10 lines + "Show 4 more"; click → 14.
  - `search shows every match` → 14 bindings, 12 of whose folders start with `C:\code\p`; search `c:\code\p` → 12
    lines, no "Show more".
  - `disables the list while a save is in flight` → fetch held pending; "Add project" and every `Remove …` disabled
    until it resolves.
- [ ] **Step 2: Run, expect FAIL** — `npx vitest run src/components/agents/__tests__/ProjectBindings.test.tsx`.
- [ ] **Step 3: Implement**; one line per binding (`grid` with the folder `truncate`; below `md` the folder wraps to
  its own line, still truncated).
- [ ] **Step 4: Run, expect PASS** — `npx vitest run`, tsc, eslint.
- [ ] **Step 5: Commit** — `feat(agents): projects as a searchable list, each change saved at once`

### Task 5: Tools tab

**Files:**
- Create: `frontend/src/components/hub/ToolsTab.tsx` (replaces `HubMachines.tsx`; move `DefaultSetSwitch` into it)
- Delete: `frontend/src/components/hub/HubMachines.tsx`
- Modify: `frontend/src/components/hub/MachineTools.tsx` (Push row sticky below `md`)
- Modify: `frontend/src/app/(app)/settings/agents/page.tsx`
- Test: `frontend/src/components/hub/__tests__/ToolsTab.test.tsx`

**Interfaces:**
- Consumes: `useHubMachines()`, `MachineTools({machine})`, Task 2 layout, `useChosenParam("machine")`.
- Produces: `ToolsTab()`; `machineState(m: HubMachine): string` in `frontend/src/lib/hub.ts` →
  `"not connected"` when offline, else `"N change(s) to push"` when `out_of_step` (N = the number of tools with a state
  other than `installed`/null; `"changes to push"` when N is 0 but `pending`), else `"up to date"`.
- Row: title = name + amber dot when `out_of_step`; meta = `"<OS label> · <machineState>"` (OS omitted when null).
- Empty: "No machines yet." with a link to `?tab=runner`.
- `MachineTools`' Push row: `max-md:sticky max-md:bottom-0` with the page background so it stays on screen.

- [ ] **Step 1: Write the failing tests**:
  - `lists machines with their state` → offline "Laptop" meta "macOS · not connected"; online out-of-step
    "Workstation" with 2 tools to change → "Windows · 2 changes to push"; online in step → "Linux · up to date".
  - `shows the chosen machine's tools` → `?machine=t2` → region `Tools on "Workstation"`.
  - `machine=new shows the first machine` → region is the first machine's.
  - `keeps the default-set switch` → the checkbox "When I add an agent on a new machine, install my default set there".
- [ ] **Step 2: Run, expect FAIL** — `npx vitest run src/components/hub/__tests__/ToolsTab.test.tsx`.
- [ ] **Step 3: Implement**; the page's Tools tab renders `<ToolsTab/>`.
- [ ] **Step 4: Run, expect PASS** — `npx vitest run` (MachineTools tests unchanged and passing), tsc, eslint.
- [ ] **Step 5: Commit** — `feat(hub): Tools tab lists machines beside their tools`

### Task 6: Runner tab and Add a machine

**Files:**
- Create: `frontend/src/lib/runner.ts` (moved from `RunnerSetup.tsx`: `Platform`, `RELEASES`, `RUNNER_INSTALL`,
  `OMP_INSTALL`, `RUNNER_UPDATE`, `R`, `detectPlatform()`, `both()`, new `platformOf(os: string | null): Platform | null`
  → `windows` → `"windows"`, `linux`/`macos` → `"unix"`, else null)
- Create: `frontend/src/components/agents/RunnerTab.tsx` (list + details), `frontend/src/components/agents/RunnerCommands.tsx`
  (one machine's day-to-day commands), `frontend/src/components/agents/AddMachine.tsx` (the steps)
- Delete: `frontend/src/components/agents/RunnerSetup.tsx`, its test (cases move, see Step 1)
- Modify: `frontend/src/components/agents/RunnerUpdateArrow.tsx` (import from `@/lib/runner`), the page
- Test: `frontend/src/components/agents/__tests__/RunnerTab.test.tsx`, `.../AddMachine.test.tsx`, `.../RunnerCommands.test.tsx`

**Interfaces:**
- Consumes: `useHubMachines()` (Task 1's `runner_version`), `RunnerUpdateArrow({runner: {version, os}, ownerId})`
  (pass `useMe()` id), Task 2 layout, `qk.tokens()` invalidation after making a token.
- Produces:
  - `RunnerTab({ onAddAgent: (machine: string) => void })`.
  - `RunnerCommands({ os: string | null })` — sections "Keep it running", "Update", "Troubleshoot" with today's
    snippets and labels (from `RunnerSetup`'s three panels), for `platformOf(os)`; a Windows / Linux-macOS toggle
    only when that is null. On `unix`, the log snippet shown is the one for the OS (Linux or macOS), both when unknown.
  - `AddMachine({ onAddAgent })` — platform toggle (`detectPlatform()`), then steps:
    1. "Name it": Input "Machine name" + "Make token" → POST (Global Constraints) → keeps `{id, secret}` in state,
       invalidates tokens and hub machines, and shows the name as done.
    2. "Install the runner": `RUNNER_INSTALL[platform]` + the GitHub download link (`RELEASES`).
    3. "Sign in": `R login --url <origin> --token <secret>` once made (placeholder `<make the token in step 1>`
       before), note "The token is shown only now. If you leave this page, make another."
    4. "Check it, then keep it running": `R doctor`; `both(platform, "R service install", "R service start")`; the Linux
       linger line on unix; "Or start it in this terminal" `R run`.
    5. A `<details>` "Using OMP agents on this machine" with today's two OMP snippets and the version note.
    - After the token is made: "Waiting for the runner to connect…" while the machines list (refetch every 3 s while
      waiting) has that token offline; then "Connected" and a button "Add an agent on it" → `onAddAgent(id)`.
- Row: title = name + green/grey dot (online); meta = `"<OS label> · runner <version> · N agents"` (version part
  omitted when null; "1 agent"), with `RunnerUpdateArrow` in `aside`. Below the list a dashed row "+ Add a machine" →
  `machine=new`.
- Details for a machine: `h2` name, "Connected"/"Not connected", OS, version, "Agents on it: …" (or "No agents on it
  yet."), then `RunnerCommands`. When offline and `reported_at` is null and no `runner_version`: the never-connected
  copy (Global Constraints) with a link "Access tokens" to `/settings/tokens`, instead of the commands.
- `machine=new`, or no machines at all → `AddMachine`. The page wires `onAddAgent` to open `AddAgentDialog` with
  `initialMachine` and switch to the Agents tab after creation (Task 3's `onCreated`).

- [ ] **Step 1: Write the failing tests**:
  - `RunnerCommands.test.tsx` — move `RunnerSetup.test.tsx`'s cases that still apply:
    `installs and starts the service in one line` (Windows `; `, unix ` && `), `updates in three steps with the
    platform's update command`, `shows the background log for the machine's OS` (macos → only the macOS log path;
    windows → the `Get-Content` line), `asks for the platform when the OS is unknown`.
  - `AddMachine.test.tsx`:
    - `makes a runner token and fills it into the sign-in command` → type "Laptop", Make token → POST body
      `{name: "Laptop", scopes: ["runner"], expires_in_days: null}`; response `{token: {id: "t9", …}, secret: "mgc_x"}`
      → a snippet contains `--token mgc_x` and this server's origin.
    - `tells OMP users how to install OMP and sign in, for their platform` (moved).
    - `waits for the runner, then offers to add an agent on it` → machines first `[{token_id: "t9", online: false}]`
      → "Waiting for the runner to connect…"; then online → "Connected"; "Add an agent on it" → `onAddAgent("t9")`.
  - `RunnerTab.test.tsx`:
    - `lists machines with version and agent count` → "Windows · runner 0.5.0 · 3 agents", "macOS · 1 agent" offline.
    - `shows the update arrow for an old runner` → latest 0.5.0 (stub `/api/updates` as `RunnerUpdateArrow.test.tsx`
      does), machine 0.4.0 → button "Runner update available".
    - `a machine that never connected says how to start over` → the verbatim copy and the Access tokens link; no
      "Keep it running".
    - `opens Add a machine from the list, and when there are no machines` → click "+ Add a machine" → `push` with
      `machine=new`; with `[]` machines the "Machine name" field shows at once.
- [ ] **Step 2: Run, expect FAIL** — `npx vitest run src/components/agents/__tests__/RunnerTab.test.tsx src/components/agents/__tests__/AddMachine.test.tsx src/components/agents/__tests__/RunnerCommands.test.tsx`.
- [ ] **Step 3: Implement**; the page's Runner tab renders `<RunnerTab onAddAgent=…/>`.
- [ ] **Step 4: Run, expect PASS** — `npx vitest run` (whole suite; `RunnerUpdateArrow` tests still pass), tsc,
  eslint.
- [ ] **Step 5: Commit** — `feat(agents): Runner tab with your machines and a guided Add a machine`

### Task 7: End-to-end specs and the phone flow

**Files:**
- Modify: `frontend/e2e/agents.spec.ts`, `hub.spec.ts`, `omp.spec.ts`, `parallel.spec.ts`, `workflow.spec.ts`,
  `mobile.spec.ts`

**Interfaces:**
- Consumes: the labels fixed in Tasks 3–6 (region named after the agent; "Add project", "Project", "Folder", "Add";
  `Remove KEY`; Tools rows and `Tools on "<name>"` region; `?tab=` and `?agent=`/`?machine=` deep links).

- [ ] **Step 1: Update the specs to the new layout**:
  - `agents.spec.ts` / `workflow.spec.ts`: after Add agent the new agent is chosen; bind with Add project → Project →
    Folder → Add, then expect the line `AGT …` with the folder; `workflow.spec.ts` removes stale bindings with
    `Remove <KEY>` + confirm instead of `Remove row`.
  - `omp.spec.ts` / `parallel.spec.ts`: `goto("/settings/agents?agent=<id>")` and scope to
    `getByRole("region", { name: AGENT_NAME })` instead of the list item card.
  - `hub.spec.ts` / `omp.spec.ts` tools part: `goto("/settings/agents?tab=tools&machine=<token id>")` (or click the
    machine's row); the `Tools on "<name>"` region assertions stay.
  - `mobile.spec.ts`: keep `/settings/agents` in the overflow sweep and add `/settings/agents?tab=tools` and
    `?tab=runner&machine=new`; bind the spec's long-named agent to its `MOB` project with a 200-character Windows
    folder (through the API, before the sweep), so the sweep checks a long folder line. Add a test `my agents on a phone: list, details,
    Back` at 375×800: the agent list shows, tapping the agent opens its details with "‹ Agents", the browser's Back and
    the "‹ Agents" button both return to the list, and nothing scrolls sideways (`overflow(page)` empty).
- [ ] **Step 2: Run the full e2e suite** on the `megoo-e2e` stack (scratchpad `e2e-run-*.sh` pattern, as plan 25 Task 7;
  never the owner's `megoocolab-*` containers). Expected: all passed.
- [ ] **Step 3: Run every suite once more**: `cd backend && uv run pytest -q > <workspace>/pytest.txt 2>&1` (all
  passed), `cd frontend && npx vitest run && npx tsc --noEmit -p . && npx eslint`.
- [ ] **Step 4: Commit** — `test(e2e): My agents tabs, side panel and the phone flow`
