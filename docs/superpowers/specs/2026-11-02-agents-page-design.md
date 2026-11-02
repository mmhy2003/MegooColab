# My agents page: tabs, list and side panel

Status: draft for the owner's review. Builds on develop as of 8f7de01.

## Why

Settings › My agents (`frontend/src/app/(app)/settings/agents/page.tsx`) is one long column today: a card per agent
with every field and every project binding laid out in full, then "Tools on your machines", then the Runner section.
With many projects under an agent the card becomes very tall, and the page is hard to use on a phone.

The owner comes to this page to do four things:

1. manage and add agents;
2. add projects under an agent (and manage them);
3. manage the tools on their machines;
4. install the runner on a new machine.

The redesign gives each of these a clear place and keeps the page short however many agents or projects there are.

## Goals

- Three tabs: **Agents**, **Tools**, **Runner**.
- Every tab uses the same pattern (the owner chose mockup **option A**): a short list on the left, the chosen item's
  details on the right. On a phone the list fills the screen and tapping an item opens its details full screen
  with a Back control.
- A long project list stays compact: searchable, shortened, one line per project.
- Adding a project to an agent is one row and saves at once.
- Adding a new machine is a guided flow that makes its runner token on the spot.
- Works well on a phone (375px wide), not just "fits".

## Non-goals

- No change to what an agent, binding, machine or tool *is*: no new settings, no new permissions.
- The Tool Hub page (`/hub`) and Access tokens page stay as they are. Access tokens remains the place to revoke a
  token.
- The admin agents page (`/admin/agents`) is not redesigned.
- No change to the runner program.

## Anti-goals

- Losing any capability the current page has (every field, command and action must still be reachable).
- A page that grows with the number of projects, or that needs sideways scrolling on a phone.
- Saving surprises: an edit that looks saved but is not, or a removal that happens with no chance to stop it.

## Layout and behaviour

### The page

- Header "My agents" with the Add agent button (shown on every tab).
- The tabs use the existing `Tabs` and `useTabParam` (`frontend/src/components/ui/Tabs.tsx`): `?tab=agents|tools|runner`,
  Agents by default. The page wraps its content in `<Suspense>` as `useTabParam` requires.
- The chosen item also lives in the address (`&agent=<id>` on Agents, `&machine=<token id>` on Tools and Runner), so a
  reload or a shared link lands on it and, on a phone, the browser's Back returns from the details to the list.
- Desktop (`md` and wider): list column about a third of the width, details beside it. With nothing chosen, the first
  item is shown.
- Phone (below `md`): the list alone; with an item chosen, the details alone, under a "‹ Agents" / "‹ Tools" /
  "‹ Runner" back link that clears the chosen item.
- The Tools tab label carries a dot while any machine is out of step with the Tool Hub (`useHubSummary`), like the
  sidebar's Tool Hub item.
- The current "Runner commands" header link (`#runner`) goes away; the Runner tab replaces it.
- An `agent` or `machine` in the address that no longer exists (deleted, revoked, stale link) is ignored: the first
  item on desktop, the list on a phone.

### Machines

A machine is a runner token of the owner (not revoked, with the Runner scope): `/api/hub/machines` lists them from the
tokens, so a token made a moment ago is in the list at once, as not connected. A machine's name is its token's name,
the same name `MachineField`, the Tools list and the Runner list show.

### Agents tab

**List row** per agent: name, status dot, "N of M running" when anything runs (`runsLabel`), and a second line with
the machine name and "N projects". The chosen row is highlighted. Empty state: "No agents yet." with Add agent and a
pointer to the Runner tab when the owner has no machines.

**Details panel**:

- Header: name, program badge, status dot, runner update arrow, and a **⋯ menu**
  (`frontend/src/components/shadcn/dropdown-menu.tsx`, already in the repo) with **Rename**, **Answer mode** and
  **Delete**.
  - Rename: a small dialog with the name field, 1–200 characters (PATCH `name`; `AgentPatch` already accepts it).
  - Answer mode: a small dialog with Manual / Auto and `ANSWER_MODE_HELP` (PATCH `answer_mode`). Today the answer mode
    can only be set when adding an agent.
  - Delete: the current confirm and DELETE.
- **Settings** section: the existing `MachineField`, `ModelField` and `RunsField`, unchanged in behaviour, laid out in
  a grid that stacks on a phone.
- **Projects (N)** section:
  - A search box (filters by project key, name or folder) and an **+ Add project** button.
  - One line per binding: project key and name, its folder, and Edit (✎) and Remove (✕) buttons. Long folders are cut
    with an ellipsis and shown in full on hover/focus (title). On a phone the folder goes on a second line.
  - The first 10 bindings, sorted by project key, are shown; then a "Show N more" button shows the rest. A search
    always shows every match.
  - **+ Add project** opens one inline row: a project select (only projects this agent isn't bound to yet), a folder
    input, Add and Cancel. Add saves at once; there is no separate "Save bindings" step.
  - **Edit** turns that line into the folder input with Save and Cancel, in place.
  - **Remove** asks for confirmation ("Remove PAY from Mo's Claude Code? The agent stops working on it."), then saves.
  - Every save PUTs the agent's whole binding list (the existing `PUT /api/agents/{id}/bindings`, built from the
    agent's saved bindings plus this one change), so there is no backend change. Folder validation stays as today
    (`isAbsolutePath`, same message). Errors show under the row being edited and keep what was typed.
  - While a save is in flight, the list's Add, Edit and Remove controls are disabled, so two quick edits cannot
    overwrite each other; after each save the agent is refetched. A change made at the same moment in another tab is
    last-write-wins, as today.
  - Empty: "Not working on any project yet." with Add project.

**Add agent** stays the same dialog with the same fields. On a phone the dialog is full screen.

### Tools tab

- Top: the existing "When I add an agent on a new machine, install my default set there" switch (`DefaultSetSwitch`).
- **List row** per machine (`useHubMachines`): name, a dot when out of step, and a second line with the OS and a short
  state: "N changes to push", "not connected", or "up to date".
- **Details**: the existing `MachineTools` panel for that machine (tick tools, Import from this machine, Push),
  unchanged in behaviour. On a phone the Push button sticks to the bottom of the screen.
- Empty: "No machines yet." with a link to the Runner tab.

### Runner tab

- **List row** per machine (the same `/api/hub/machines` list): name, connected dot, and a second line with OS, runner
  version (with the update arrow when older than the latest release) and "N agents". Below the list a dashed
  **+ Add a machine** row.
- The backend adds the connected runner's version to `HubMachineOut` (`runner_version: str | None`, from the
  connection's hello, None while offline) so a machine without agents still shows its version. The update arrow is
  the existing `RunnerUpdateArrow`, given `{version: runner_version, os}` built from the machine (it already compares
  with the latest release from `useUpdates`).
- **Machine details**: whether it is connected, its OS, version, the agents on it, and the day-to-day commands that
  `RunnerSetup` has today under Keep it running, Update and Troubleshoot, for that machine's platform (taken from the
  machine's reported OS; a toggle when it has never connected).
- A machine that has never connected (`reported_at` empty and offline) says so in its details: "This machine hasn't
  connected yet. Its token was shown once when you made it; if you no longer have it, set the machine up again with
  Add a machine and revoke this one under Access tokens." with a link to Access tokens.
- **Add a machine** (also the Runner tab's view when the owner has no machines) is `&machine=new` in the address, so
  the first machine is not auto-chosen over it and a phone's Back returns to the list. What was typed and the new
  token live only in the page's memory: a reload starts the steps again. It walks through steps with a platform
  toggle (detected as today):
  1. **Name it**: a name field and **Make token**. This creates a runner token (`POST /api/tokens` with scope
     `runner`, never expiring, as the Access tokens page can), shown once. The name is the machine's name.
  2. **Install the runner**: the install command (and the GitHub download link).
  3. **Sign in**: the login command with this server's URL and the new token filled in, with a note that the token
     is shown only now. Leaving the page loses it; the owner then makes another (the old one can be revoked under
     Access tokens).
  4. **Check it, then keep it running**: `doctor`, then the service install and start commands (and the Linux linger
     line), with "or start it in this terminal" (`run`) as the alternative.
  5. Optional, folded away: "Using OMP agents on this machine" with the OMP install and sign-in commands.
  - Under the steps: "Waiting for the runner to connect…" until the new token's row in the machines list is online
    (the list refetches while this view is open), then "Connected" with **Add an agent on it**, which opens Add agent
    with that machine (the new token id) chosen.

## Constraints

- Frontend only, apart from `runner_version` on `HubMachineOut`.
- Reuse the existing components where the behaviour stays the same (`MachineField`, `ModelField`, `RunsField`,
  `MachineTools`, `Snippet`, `RunnerUpdateArrow`, `Dialog`, `ConfirmDialog`, `Tabs`). `BindingEditor` and
  `RunnerSetup` are replaced; their tests move with them.
- Copy stays plain and short, in the voice the page already uses.
- Keyboard and screen readers: tabs as today; list rows are buttons or links with the chosen one marked
  (`aria-current`); the ⋯ menu has an accessible name ("Actions for <agent>").
- The e2e specs that drive this page (`agents`, `hub`, `mobile`, `omp`, `parallel`, `workflow`) are updated to the new
  layout; `mobile.spec.ts` checks the phone flow (list → details → Back) and that nothing scrolls sideways at 375px.

## Calls I made (the owner can overrule)

- Projects show 10 lines before "Show N more".
- Removing a project asks for confirmation; adding and editing save at once.
- Answer mode becomes changeable after an agent is created, through the ⋯ menu.
- Tokens made by Add a machine never expire.
- The Runner tab shows the runner's version per machine, which needs the one backend field.
- Add a machine is `&machine=new`; its token is kept only in memory, and a machine that never connected explains how
  to start over.
- Binding edits lock the list while saving; concurrent edits elsewhere stay last-write-wins.
- Status: draft → approved once the owner says so.

## Left to the builder

- Component and file names, and how the list/detail pattern is shared between the three tabs.
- Exact spacing, breakpoints within reason (`md` is the split), and icons.
- How long the "waiting to connect" refetch interval is.
