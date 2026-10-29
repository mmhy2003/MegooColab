# Branch from: where an agent starts its work and where it delivers it

## Why

Some of our projects keep two long-lived branches: `develop` (development and staging) and `main` (production).
Others only have `main`. Today an agent's branch starts from whatever the developer's local checkout happens to
have checked out when the run starts, and the finish run has to guess the target from "the project's default
branch", a value it is never given. A developer who happens to be on an old feature branch gets an agent that
builds on top of it, and nothing lets a person say "this bug is a production fix: start from `main`".

We do not want git-flow naming (`feat/`, `fix/`, `hotfix/`). Agents keep their `megoo/<KEY>-<slug>` branches in
their own worktree; that stays exactly as it is. What we want is control over the two things git-flow is really
about: which branch the work starts from, and which branch(es) it goes back into.

## Goals

1. Every agent run starts its task branch from a known branch, the repository's **default branch**, never from
   whatever is checked out locally.
2. A task can name a different branch to start from (**Branch from**), for example `main` for a production fix
   on a project whose default branch is `develop`.
3. The finish run delivers into the branch the work started from. When that is not the default branch, it also
   brings the same fix into the default branch (the back-merge), resolving conflicts itself.
4. The task page says, in plain words, where the work starts and where it will be delivered.

## Non-goals

- Branch name prefixes or naming by task type. Branch names stay `megoo/<KEY>-<slug>`.
- A new task type for hotfixes. Bug stays one type; Branch from decides where it goes.
- Several repositories in one project, each with its own local folder (a separate, later piece).
- Agents creating epics, stories or sprints (a separate, later piece).
- Release branches as a concept. Branch from accepts any branch name, so a release branch works, but nothing is
  built around them.

## Anti-goals

- An agent must never start from a stale local copy when the remote is reachable.
- A production fix must never be finished while it is only in `main`: if it is not in the default branch too,
  the task is not done.
- Changing Branch from after work has started must not leave an agent's branch and its target pointing at
  different places.

## Decided by the user

- Projects either have `develop` + `main` or only `main`. The project's repository "Default branch" setting is
  where `develop` (or `main`) is named.
- No git-flow naming; worktrees keep isolating the work.
- A production fix is merged into `main` and also into `develop`.
- If bringing the fix into `develop` conflicts, the agent resolves the conflict itself (it does not stop and ask).

## How it works

### The start branch

- **Default branch.** The default branch used here is the `default_branch` of the project repository that the
  agent's bound folder belongs to. *(My call:)* the runner matches the folder's `origin` remote URL against the
  project's repositories (`ProjectRepository.url`, compared the way PR tracking already normalises repository
  paths). If none matches and the project has exactly one repository, that one is used. If the project has no
  repositories, or several and none matches, the run falls back to today's behaviour (current `HEAD`) and says
  so in the run log, so nothing that works today breaks.
- **Branch from** is a new optional field on a task: a branch name. Empty means "the default branch". It is
  validated as a git branch name (`git check-ref-format --branch` rules), at most 200 characters.
- **Fetching first.** Before creating a task's worktree, the runner fetches the start branch from `origin` and
  creates the task branch from `origin/<start branch>`. *(My call:)* if the folder has no `origin`, or the fetch
  fails (offline), it uses the local branch of that name and notes it in the run log. If neither exists, the run
  fails with a clear error naming the branch (`start_branch_missing`).
- **Existing worktrees are unchanged.** A task whose worktree or branch already exists is reused as today; the
  start branch only matters when the branch is first created.
- **A default branch that does not exist** *(my call)*: existing repositories may carry the unchecked `"main"`
  default while their real branch is `master`. When the start branch is the *implicit* default and it exists
  neither on `origin` nor locally, the runner falls back to `origin/HEAD`, then to the current `HEAD`, and says so
  in the run log. Only an *explicit* Branch from that does not exist fails the run (`start_branch_missing`).
- **Branch from set, but no repository matched** *(my call)*: without a known default branch nobody can tell
  whether a back-merge is needed, so the run fails with `repository_not_matched`, naming the folder's remote and
  the project's repositories, instead of finishing a production fix in one branch only. An empty Branch from with
  no matched repository keeps today's behaviour (above).
- **Fixed once created** *(my call)*: when the task branch is first created, the run records the resolved start
  branch and default branch on the task's workflow (or the task, for runs without a workflow). Later runs,
  the finish prompt and the task page read those recorded values, so changing a repository's Default branch, or a
  later run going to an agent whose folder matches a different repository, cannot move an in-flight task's target.
  Recording only happens once the branch really exists, so a `start_branch_missing` typo stays fixable.
- **Older runners** *(my call, following the `workflow/1` precedent)*: the start branch is a new runner
  capability. Runs on a runner without it stay queued with a visible "this runner needs updating" reason, rather
  than starting from `HEAD`.
- **Connect-only workflows** *(my call)*: personal-token agents have no runner worktree or finish run. For them
  `get_workflow` reports the start branch and the back-merge branch so the agent knows where to work and deliver;
  nothing is enforced, and Branch from locks when the workflow starts.
- **This applies to every run that creates a worktree**, workflow-driven or not.

### Locking

*(My call:)* Branch from can be edited by anyone who can edit the task, until the task's branch has been created
(the first run that created a worktree started). After that it is read-only, and the API refuses a change with
`branch_from_locked`. The field shows why it is locked.

### Delivering (the finish run)

The finish run's prompt no longer tells the agent to work out the base. It states the values explicitly, outside
untrusted blocks:

- the start branch (where the work goes);
- the back-merge branch, when the start branch is not the default branch (the default branch).

Per finishing option:

| Option | Start branch = default branch | Start branch ≠ default branch (production fix) |
|---|---|---|
| Pull request | One PR into the default branch (as today). | PR 1: task branch into the start branch. PR 2: a back-merge branch into the default branch (below). |
| Merge locally | Merge into the default branch (as today). | Merge into the start branch, then into the default branch, in the developer's main checkout, re-running tests after each. |
| Keep branch | Nothing merged or pushed (as today). | Nothing merged or pushed. The task page notes that the fix still needs to reach both branches. |
| Plain git (no provider) | Push the task branch (as today). | Push the task branch and the back-merge branch. |

**The back-merge branch** *(my call)*: for a pull request, the agent creates `megoo/<KEY>-<slug>-to-<default>`
from `origin/<default branch>`, merges the task branch into it, resolves any conflicts, runs the full test suite,
and opens PR 2 from it. Merging the task branch straight into the default branch in a PR would show unresolved
conflicts, and a separate branch keeps the resolution reviewable. For merge-locally the merge into the default
branch happens directly in the main checkout.

**Resolving conflicts.** This is the one place the finish stage changes code. The finish methodology text gets an
exception for it: the agent may resolve merge conflicts in the back-merge only, keeping the intent of both sides,
must run the full suite on the result and record it (`record_tests`), and must record each conflicted file and
how it resolved it with `record_decision`. If the suite fails after resolution and it cannot fix it within the
same three-attempt rule the text already has, it falls back to `ask_human`. *(My call:)* in pull-request mode the
resolution is reviewed by whoever merges PR 2; in merge-locally mode there is no extra review, and the recorded
decisions are the trace.

**Reporting.** `report_finish` gains an optional back-merge result (its branch and, for a PR, its URL). It is
required when the task has a back-merge and the option is pull request, merge locally or plain git, and refused
otherwise. Both PRs are tracked (the one-PR-per-task model becomes up to two per task, each marked as main or
back-merge).

**When the task is done.**

- No back-merge (the work started from the default branch): unchanged from today. Without human code review the
  workflow finishes when the finish run reports; with it, it waits on the one PR.
- **A production fix in pull-request mode (decided by the user): the task always waits until both PRs are merged,
  whether or not the project requires human code review.** It waits in the same `human_code_review`-style state
  the review case uses today, so both PRs are tracked and the existing merge and close handling applies. An
  untracked PR (no connection follows it) is finished by a person's "Mark merged", as today. If either PR is
  closed without merging, the existing `pr_closed` escalation is raised, naming which one. Where human code review
  is required, "PR approved" in MegooColab applies to both.
- Merge locally and plain git with a back-merge: finished when the finish run reports both merges or pushes.

### What people see

- **Task detail:** a "Branch from" field, with the default branch as its placeholder (for example "develop
  (default)"). Under the workflow's finishing section, one plain line: "Starts from `main`. Delivers to `main`,
  then `develop`." or "Starts from `develop`. Delivers to `develop`."
- **After finishing:** both branches and both PR links (when there are two), each with its tracked state.
- *(My call:)* a small badge on the board card ("from main") only when Branch from is set to something other than
  the default, so production fixes stand out on the board.

### Protocol

`run_start` carries the start branch (the resolved branch name, or empty for "use HEAD as today" when no
repository can be matched). *(My call:)* the server resolves Branch from or the matched default; because the
server cannot see the folder's remote, the runner sends the folder's `origin` URL per binding when it connects,
and the server picks the repository. The builder may instead send all of the project's repositories and let the
runner match; either is fine as long as the run log says which repository and branch were used.

## Constraints

- Branch names stay `megoo/<KEY>-<slug>`; the back-merge branch adds `-to-<default branch>` (slugged).
- No force pushes, no history rewriting; the existing hard rules in the finish text stay.
- Task text remains untrusted: only the prompt's explicit start and back-merge branches decide where the agent
  delivers. The finish text's "unless the task says otherwise" goes away.
- Existing projects and tasks keep working: an empty Branch from means the default branch, and an unmatched
  repository means today's behaviour.
- Migrations follow the project's usual Alembic flow.

## Left to the builder

- The exact shape of the `report_finish` extension and of the second PR row.
- How the runner and server exchange the folder's remote (see Protocol).
- Wording of the new finish-text section, within the rules above.
- Whether Branch from is also settable through the MCP `create_task`/`update_task` tools (optional; nice for
  personal-token agents, not required).
