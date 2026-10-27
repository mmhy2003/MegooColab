# Live mockups, decision and test records, and fuller methodology texts — design

**Date:** 2026-10-27
**Builds on:** `docs/brd.md` (WF-5, WF-6c, WF-6d, WF-9, WF-10, NFR-2, NFR-3, NFR-4) and merged Plans 1–7.
**Not in this design:** Meilisearch. It is a separate project with its own design, to follow.

## 1. Why

MegooColab runs the superpowers method for coding agents. Comparing what we ship with the upstream skills
and their local `.superpowers/` folder left three gaps that matter to people using the platform:

1. **Iterating on a design by eye is clumsy.** An agent can show an HTML mockup only by attaching it to a
   question, and a person only sees a new version after reopening the task. The owner's usual loop is "show
   me, change this, show me again, … approve". They want the screen to update by itself as the agent works,
   and want approving the version they like to be the same as approving the design.
2. **What an agent decided on its own, and what its tests actually said, is lost.** Upstream keeps a ledger of
   "rulings" (the plan said X, I did Y, because Z, and this is what it costs if I'm wrong) and test output on
   the developer's machine. MegooColab is the shared hub, so these belong on the platform where the team and
   the reviewers can see them. Today a step reports only "tests passed: yes/no" plus a command, and any
   deviation is buried in free-text summaries.
3. **Three disciplines are thin or missing in our instruction texts.** systematic-debugging is missing (an
   agent whose tests fail just asks a person). test-driven-development and verification-before-completion are
   down to a few lines and miss upstream's list of excuses that agents use to skip them.

Success: the owner can iterate on a mockup with an agent and approve it from the mockup itself. Every task shows
the agent's own decisions and its recorded test runs, and reviewers judge both. Agents debug before they give up.

## 2. Goals, non-goals, anti-goals

**Goals**
- A: Agents can show a new mockup version at any point in Brainstorm or a design revision without asking a
  question or ending their turn. Everyone looking at the task sees it within about 2 seconds (NFR-4).
- A: In the task view, people can flip between versions, compare two side by side, give feedback, and approve
  the version the design was submitted with. **Approving the version approves the design** (owner's decision).
- B: Agents record each decision they make on their own as a structured entry, shown on the task.
- C: Agents record each test run as a structured entry (command, counts, failing test names), shown on the task.
- D: Instruction texts gain systematic debugging, full TDD and verification-before-completion, and tell agents
  to use B and C and to record corrected facts in the Knowledge Base.

**Non-goals**
- Meilisearch (next design).
- dispatching-parallel-agents: steps share one worktree, so parallel steps would collide.
- executing-plans: MegooColab is the executor; it already runs the subagent-driven flow.
- Keeping full test logs, diffs, review packages or task briefs on the platform. Logs and diffs are raw output
  and code, which NFR-2 keeps on the developer's machine. Briefs and packages can be rebuilt from the plan and
  git.
- People editing a mockup themselves.
- Mockups outside Brainstorm and design revision.

**Anti-goals** (failure even if it works)
- Any code, diff or raw command output reaching the server (NFR-2).
- A mockup able to read MegooColab's session, cookies or API, or call the network (WF-6d sandbox stays as is).
- Agent-written text (decisions, test names) reaching a later agent as instructions rather than data (NFR-3).
- A person approving a design they could not see: the version they approve must be the one the design was
  submitted with.

## 3. Part A — live mockups

### What the agent does
- New MCP tool **`show_mockup(key, html, title)`**. It stores the next mockup version for the task and returns
  `{version}`. It does not end the turn and asks nothing.
  - Allowed for the `brainstorm` role, which also covers the same session resumed to revise a rejected design.
    Connect-only agents with a personal token may use it in Brainstorm and Design.
  - Same limits and validation as mockups on questions today: 2 MB, a title of up to 200 characters, and the
    same sandboxed rendering.
  - At most 50 mockup versions per task, counting both kinds. The 51st is refused with `too_many_mockups`.
  - **Refused with `design_submitted`** while the task has a design awaiting approval. That covers a runner
    session that keeps going after its own `submit_design`, and a connect-only agent whose design waits in
    Design. A new picture comes only after a person asks for changes. The revising session then shows new
    versions and resubmits, and the resubmitted design links to the new newest version. This keeps the anti-goal:
    the version a person approves is always the one the pending design was submitted with.
- `ask_human` keeps its `mockup_html` / `mockup_choices` arguments unchanged. Clickable choices
  (`data-megoo-choice`) exist only on question mockups, because only a question has somewhere to send the click.
- When the agent submits a design, the design is **linked to the newest mockup version that exists at that
  moment**, if there is one. This is in addition to today's "chosen through a question" attachments
  (`attached_mockup_ids`).

### What people see
- The task view gets a **mockup panel** in the workflow area, shown once the task has at least one mockup:
  - The newest version, rendered inline in the existing sandboxed frame, with its title and "v3 of 3".
  - A version switcher, **Compare** (two versions side by side on wide screens, stacked on narrow ones) and
    **Open full screen**.
- **Live updates.** A new version arrives as a task event, and the realtime layer already refreshes the
  `["mockups"]` queries. The panel jumps to the new version. The exception is when the person is looking at an
  older version: then a "v4 is ready" pill appears instead, so their view doesn't change under them.
- The thread and activity record each version: "Claude Code showed mockup v3: Settings page, compact".
- **Feedback box** under the panel. What it does depends on what the workflow is waiting for:
  - An open question: the text answers that question, so the same session resumes with it.
  - A design awaiting approval: the text is a **Request changes**, i.e. a design rejection with that comment.
    The same brainstorm session resumes and revises the design (already how WF-8 works). The agent shows new
    mockup versions and resubmits.
  - Otherwise the box is disabled with "The agent is working. You can reply when it asks a question or submits
    the design."
- **Approve this version** appears only when a design is awaiting approval, and only on the mockup version that
  design is linked to. Clicking it is the same as approving the design: the same roles, the same "first decision
  wins", the same filing, the same decision endpoint. Older versions show "Older version" and cannot be approved.
  The design document's own **Approve** button stays too, since the document now shows its linked mockup inline.
  Both approve the same design version. A design submitted without any mockup is approved the way it is today.
- The design document view shows its linked mockup inline instead of only a link.
- **Knowledge Base filing (WF-6d).** When a design is approved, the filed design revision ends with a line
  naming the approved mockup version and linking to its view URL. The HTML itself stays in the mockups table;
  KB documents are markdown.

## 4. Part B — decision records

- New MCP tool **`record_decision(key, decision, reason, cost_if_wrong, plan_said?)`**.
  - Text limits: `decision`, `reason` and `plan_said` up to 1,000 characters each; `cost_if_wrong` up to 500.
  - Allowed roles: `implement`, `step_fix`, `final_fix` and `finish`. Connect-only agents may use it during Build.
  - At most 30 per step. For `final_fix` and `finish`, "per step" means per stage.
  - The server fills in the task, stage, step and time, and the run and agent when there is one. Connect-only
    workflows have no run and no agent row. Their records carry no run, and the label shows the person whose
    connected agent posted them ("Sam's connected agent").
  - Brainstorm and plan agents don't use it: their calls belong in the design and plan documents they submit.
- **Shown on the task** as a **Decisions** section, grouped by step. Each entry shows the agent, step and time,
  and its four fields. The workflow panel shows a count ("3 decisions"). People who disagree reply in the thread.
  Entries are read-only and there is no accept/reject state.
- **Reviewers judge them.**
  - The step reviewer's prompt includes that step's decisions.
  - The final reviewer's prompt includes all of them.
  - Both texts tell the reviewer to judge each decision: does it stand, or is it a finding?
  - Decisions are wrapped as untrusted content (NFR-3).
- **Memory.** Decisions are explicit agent-posted text, so they become a memory source like run summaries
  (allowed by NFR-2).

## 5. Part C — test-run records

- New MCP tool **`record_tests(key, command, passed, total?, failed?, skipped?, failing?)`**.
  - `command` up to 200 characters. The counts are non-negative integers.
  - `failing` lists up to 20 test names of up to 300 characters each. **Names only, never output.**
  - Allowed roles: `implement`, `step_fix`, `final_fix` and `finish`. Connect-only agents may use it during
    Build. Reviewers are left out: their sessions are read-only and cannot run the project's code (runner
    policy), so they judge the recorded runs instead.
  - At most 50 per step (per stage for `final_fix` and `finish`). The server fills in the task, stage, step and
    time, and the run and agent when there is one (see Part B for connect-only).
- **Shown on the task.**
  - Each plan step in the checklist shows its latest test run: "✓ 142 passed — `uv run pytest`", or "✗ 3 failed:
    test_a, test_b, test_c". The step's other runs are behind a disclosure.
  - The Done stage shows the finish run's verification the same way.
- **Soft check, not a gate.** If `complete_step` claims `tests_passed=true` but no passing test run was recorded
  for that step since the step's previous `complete_step` (or since the step began), the step shows "No test run
  recorded". This works the same with or without a run. `complete_step` is not refused, so connect-only agents and older
  runners keep working. `complete_step`'s own `tests_passed` / `test_command` stay as they are.
- Reviewers' prompts include the recorded test runs for the step (step review) or the whole task (final review).
  They are untrusted content.

## 6. Part D — instruction texts

Each of these is a new default text, with its hash appended in `methodology_history`. Only texts nobody
customised are upgraded, as today. These disciplines are written into each text that needs them, not added as
shared texts, so each run still runs exactly one versioned text (WF-10).

| Text | Changes |
|---|---|
| `brainstorm`, `design_revision` | When to use `show_mockup` versus a question with a mockup. The loop: show, ask what to change, show again, then submit the design once the person is happy. Show the version you are submitting last, because the design links to the newest one. |
| `build_implement` | Full TDD with upstream's excuses table (condensed). A **"When something fails"** section with systematic debugging: (1) read the error and reproduce it, (2) trace to the root cause, (3) one hypothesis and one minimal change at a time, (4) after three failed fixes, stop, question the approach, and `ask_human` with what was tried. **Verification before completion**: run the command fresh, read the output, `record_tests`, and only then `complete_step`. `record_decision` whenever the step departs from the plan or settles something the plan left open. `kb_write` when the design, the KB or memory turns out wrong about the code. |
| `build_step_fix`, `review_fix` | The same debugging, verification and decision sections. Disagreeing with a finding is recorded as a decision. |
| `finish` | Verification and debugging when tests fail on the merged result. `record_tests` for the verification run. |
| `build_step_review`, `review_final` | Read the recorded decisions and test runs. Judge each decision. A step that claims passing tests with no recorded run is a finding. |

## 7. Constraints

- NFR-2: only text the agent explicitly posts reaches the server. That means mockup HTML (already allowed),
  decision text, and the test command, counts and names. No output, diffs or files.
- NFR-3: decisions and test names are wrapped as untrusted content in every later prompt.
- NFR-4: a new mockup version, decision or test run is visible to viewers within about 2 seconds, through the
  existing task-event realtime path.
- The WF-6d sandbox, its 2 MB limit and its view endpoint are unchanged.
- Run tokens keep their role checks (`TOOL_ROLES`). Each new tool re-checks under the workflow lock that the run
  is still running, as the existing tools do.

## 8. Calls I made (the owner didn't decide these)

1. The Approve-this-version button only appears on the version the submitted design is linked to (the newest
   one when it was submitted), so nobody approves a picture the design text doesn't match.
2. The feedback box reuses existing paths (answer the open question, or reject the design with a comment), so
   there is no new way to wake an agent mid-run.
3. Shown mockups have no clickable choices.
4. A cap of 50 mockup versions per task, 30 decisions per step and 50 test records per step.
4a. No new mockups while a design awaits approval. Changes go through "Request changes" and a resubmission.
4b. Both Approve buttons (mockup panel and design document) stay, and both use the same endpoint.
4c. Reviewers don't record tests, because they cannot run them. They judge the recorded runs.
4d. Records from connect-only agents carry no run and are labelled with the person's name.
5. Disciplines are written into each text instead of shared texts, to keep one versioned text per run.
6. A missing test record is a visible warning, not a refusal.
7. Decisions are read-only; people discuss them in the thread.
8. The KB gets a link to the approved mockup, not the HTML.
9. Decisions feed memory.

## 9. Left to the builder

- Table and column names, migrations, and response shapes.
- The panel's exact layout and copy beyond what is quoted above.
- How the reviewer prompts lay out decisions and test runs.
- The condensed wording of the TDD excuses table and the debugging phases, as long as each phase above is kept.
