# Pull request and branch events on the task's Activity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a task's Activity shows each push, PR opened, comment, review, checks result, merge and close on its
branch or pull request, with who acted (agent or person) and the host.

**Architecture:**
- A pure parser turns a verified webhook delivery into `GitEvent`s.
- A recorder maps each event to a task (by `megoo/<KEY>` branch, a seen PR, or a tracked PR) and works out the
  actor (an agent run on the task, or the host's name). It folds review comments into their review and writes
  `TaskEvent` rows of `git.*` kinds.
- Checks come from the existing PR refresh.
- The Activity query hides `pr.status`, and hides a nameless merge or close when a named one exists.
- The frontend renders `git.*` kinds with an icon, the actor, an agent tag, a host chip, an excerpt and links.

**Tech Stack:** FastAPI, SQLAlchemy async + Alembic, pytest with httpx; Next.js 16, React 19, Tailwind 4, vitest,
Playwright, lucide-react.

**Spec:** `docs/superpowers/specs/2026-11-03-git-activity-design.md`

## Global Constraints

- **Branches:** a task's branches are `megoo/<KEY>-<slug>` and `megoo/<KEY>-<slug>-to-<branch>`. A branch belongs to
  task `<KEY>` when it matches `^megoo/([A-Za-z][A-Za-z0-9]{1,9}-\d+)(?:-|$)` (the key is upper-cased).
- **The repository** must be one of the task's project's repositories, on the delivery's connection, with the same
  path.
- **Agent window:** an agent run on the task that is running, or finished within **5 minutes**. Only pushes and PRs
  opened are attributed to an agent.
- **Limits:** excerpts are at most **280** characters, with whitespace collapsed and "…" when cut. At most **3**
  commit titles are kept.
- **One entry each:** per push, per review (line comments folded in), and per head commit and checks result.
- **Never stored:** raw payloads, tokens or secrets.
- **Phone:** entries fit **280 px** with no sideways scroll.
- **Migrations:** generated only against `megoo_migrate`, with
  `DATABASE_URL=postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_migrate` and a throwaway `SECRET_KEY`.
- **Tooling:** run ruff from `backend/`. Never two pytest runs at once. No Prettier.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Activity text:**
  - "pushed N commit(s) to `<branch>`", plus " · PR #n updated" when the branch has an open PR MegooColab knows of
  - "opened PR #n · `<head>` → `<base>`"
  - "commented on PR #n"
  - review: "approved PR #n", "requested changes on PR #n", or "reviewed PR #n"
  - "Checks passed on PR #n" or "Checks failed on PR #n"
  - "merged PR #n", or "closed PR #n without merging"
  - host chips: "GitHub", "GitLab", "Gitea"
  - the agent tag: "agent"

## Review Focus

1. **A `megoo/<KEY>` branch in a repository that `<KEY>`'s project doesn't have:** ignored. Nothing is recorded on
   that task. Pinned in Task 2 by `test_a_branch_of_a_project_without_this_repository_is_ignored`.
2. **A delivery through repository A's own address that names repository B:** ignored for Activity. The PR refresh
   still works as before. Pinned in Task 2 by `test_a_delivery_naming_another_repository_is_ignored`.
3. **A review's line comment arriving before the review itself:** one entry. Its verdict and summary are filled in
   when the review arrives. Pinned in Task 2 by `test_a_line_comment_before_its_review_makes_one_entry`.
4. **A merge seen by the poll first, then by the webhook,** and the other way round: one merge line in Activity, the
   named one. Pinned in Task 3 by `test_one_merge_line_whichever_comes_first`.
5. **Unexpected payload shapes** (missing `commits`, `null` objects, non-string titles): 204, no crash, nothing
   recorded. Pinned in Task 1 by `test_odd_payloads_parse_to_nothing`.

---

### Task 1: Parse a delivery into events

**Files:**
- Create: `backend/app/git/events.py`
- Test: `backend/tests/git/test_events.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class GitEvent:
      kind: str                # git.pushed | git.pr_opened | git.commented | git.reviewed | git.review_comment | git.pr_merged | git.pr_closed
      path: str                # repository path, e.g. "acme/pay" or "grp/sub/pay"
      number: int | None       # the PR (None for a push)
      branch: str | None       # push: the branch; PR events: the PR's head branch when the payload has it
      actor: dict              # {"name": str, "login": str | None}
      data: dict               # per kind, below

  def parse_delivery(kind: GitKind, headers: Mapping[str, str], payload: object) -> list[GitEvent]
  def excerpt(text: object, limit: int = 280) -> str
  ```
- `data` per kind:
  - `git.pushed`: `{commits: int, titles: list[str], head_sha: str, compare_url: str | None}`
  - `git.pr_opened`: `{url, title, base}`
  - `git.commented`: `{url, excerpt, file?, line?}`
  - `git.reviewed`: `{review_id: str | None, verdict: "approved" | "changes_requested" | "commented", excerpt, url}`
  - `git.review_comment`: `{review_id: str, file, line, excerpt, url}`
  - `git.pr_merged` and `git.pr_closed`: `{url}`
- The event header is `x-github-event` for GitHub, `x-gitlab-event` for GitLab, and `x-gitea-event` for Gitea.
  Gitea also sends `x-github-event`, so read `x-gitea-event` first for Gitea.
- What each provider maps from (anything else gives `[]`):
  - **GitHub:**
    - `push`: skip when `deleted` is true. Branch from `refs/heads/…`, then `commits[].message`, the actor from
      `pusher.name`, then `after` and `compare`.
    - `pull_request`:
      - `opened` gives `git.pr_opened`, from `pull_request.{number, html_url, title, head.ref, base.ref}`.
      - `closed` gives `git.pr_merged` when `pull_request.merged`, else `git.pr_closed`.
      - The actor is `sender.login`.
    - `issue_comment` with `created` and `issue.pull_request` present gives `git.commented`, with no file.
    - `pull_request_review` with `submitted` gives `git.reviewed`:
      - `review.state` maps lower-case to a verdict: `changes_requested`, `approved`, anything else `commented`.
      - Skip a `commented` review whose body is empty: only its line comments carry content, and they fold into it.
    - `pull_request_review_comment` with `created` gives `git.review_comment`, from
      `comment.{pull_request_review_id, path, line or original_line, body, html_url}`.
  - **GitLab:**
    - `Push Hook`: skip when `after` is all zeros. Uses `commits[].message`, `total_commits_count`, `user_name` and
      `user_username`.
    - `Merge Request Hook`, by `object_attributes.action`:
      - `open` gives opened, `merge` gives merged, `close` gives closed;
      - `approved` gives `git.reviewed` with verdict `approved`, using `object_attributes.{iid, url, title,
        source_branch, target_branch}` and `user.{name, username}`.
    - `Note Hook` with `noteable_type == "MergeRequest"` gives `git.commented`, with `position.new_path` and
      `new_line` when present, `merge_request.{iid, source_branch}` and `object_attributes.{note, url}`.
  - **Gitea:**
    - `push`: as GitHub, with the actor from `pusher.full_name` or `login`, and `compare_url`.
    - `pull_request`: as GitHub, with the actor from `sender.full_name` or `login`.
    - `issue_comment`: when `is_pull` is true or `issue.pull_request` is set, gives `git.commented`.
    - `pull_request_review_approved`, `_rejected` and `_comment` give `git.reviewed`, with verdict `approved`,
      `changes_requested` or `commented` and `review.content` as the summary.

- [ ] **Step 1: Write the failing tests** in `tests/git/test_events.py`, one per mapping, each with a minimal
  payload dict:
  - `test_github_push`: 2 commits on `refs/heads/megoo/PAY-7-retries` give one `git.pushed` with branch
    `megoo/PAY-7-retries`, `commits == 2`, the first line of each message in `titles`, and actor `{"name": "mo",
    "login": "mo"}`.
  - `test_github_push_deleting_a_branch_is_nothing`.
  - `test_github_pr_opened_merged_closed`: three actions give the three kinds, with `branch == head.ref`.
  - `test_github_comment_review_and_line_comment`: the review verdicts map; a line comment carries `review_id`,
    `file` and `line`; an empty `commented` review gives `[]`.
  - `test_gitlab_push_mr_and_note`: a nested path `grp/sub/pay`; a diff note carries `file` and `line`; `approved`
    gives an approved review.
  - `test_gitea_push_pr_and_reviews`: the `_rejected` event gives `changes_requested`.
  - `test_excerpt_collapses_and_cuts`: `excerpt("a\n\n  b" + "x" * 400)` starts with `"a b"`, its `len` is ≤ 280,
    and it ends with `"…"`.
  - `test_odd_payloads_parse_to_nothing`: these all give `[]` and never raise:
    - `None`, `[]`;
    - `{"commits": None}`;
    - `{"pull_request": None, "action": "opened"}`;
    - a push whose `commits` is `"x"`, and a title that is `5`.
- [ ] **Step 2: Run** `uv run pytest -q tests/git/test_events.py`. Expected: it fails with
  `ModuleNotFoundError: app.git.events`.
- [ ] **Step 3: Implement `events.py`.** Small helpers `_dict(v)`, `_str(v)` and `_int(v)` guard every read, as
  `_about` in `router.py` does. Titles are the first line of each message, through `excerpt`.
- [ ] **Step 4: Run it.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(git): read pushes, pull requests, comments and reviews from a delivery`.

### Task 2: Record events on the task

**Files:**
- Modify: `backend/app/git/models.py`. Add `GitPrLink`: table `git_pr_links`, with:
  - `connection_id` (FK `git_connections`, cascade), `path String(500)` and `number int`, which together are the
    primary key;
  - `task_id` (FK `tasks`, cascade, indexed);
  - `url Text`, `head_branch String(255)|None`, `open bool`.
- Create: `backend/migrations/versions/<rev>_git_pr_links.py`. Autogenerate it against `megoo_migrate`.
- Create: `backend/app/git/activity.py`.
- Modify: `backend/app/git/router.py`. In `_handle`, after the refresh queueing, call
  `await activity.record(db, conn, events.parse_delivery(GitKind(conn.kind), request.headers, payload), repo=repo)`.
  Pass the repository from `receive_repository_webhook`, and `None` from the shared address.
- Test: `backend/tests/git/test_activity.py`, through the webhook endpoints, using `_world` in the style of
  `tests/git/test_repo_webhooks.py`.

**Interfaces:**
- Consumes: Task 1's `GitEvent`, `parse_delivery`.
- Produces:
  ```python
  async def record(db, conn: GitConnection, events: list[GitEvent], *, repo: ProjectRepository | None) -> int  # entries written or updated
  async def agent_actor(db, task: Task) -> dict | None   # {"kind": "agent", "agent_id": str, "name": str} or None
  def task_key_of(branch: str | None) -> str | None
  ```
- **Stored `TaskEvent.data`:**
  - `{host: conn.kind, actor: {"kind": "agent"|"person", "name", "login"?, "agent_id"?}, pr: {"number", "url"} | None,
    **event.data}`
  - plus `branch` on `git.pushed` and `git.pr_opened`, and `head` and `base` on `git.pr_opened`.
  - `actor_user_id` is None.
  - Written through `app.workflow.engine.record_workflow_event`, which publishes `task.updated`.
- **Task lookup, in order:**
  1. `task_key_of(event.branch)` names a task whose project has a `ProjectRepository` on `conn` with
     `repo_path(url) == event.path`.
  2. A `GitPrLink` for `(conn.id, path, number)`.
  3. A `TaskPullRequest` on `conn` whose URL parses to `(path, number)`.
- **The links table:**
  - `git.pr_opened` (and any PR event found by branch) upserts a `GitPrLink` with `open=True`.
  - Merged and closed set `open=False`.
- **Through a repository's own address:** an event whose `path` isn't that repository's path is dropped.
- **Pushes:**
  - " · PR #n updated" data comes from an open `GitPrLink` with `head_branch == branch`. Store `pr` when found.
- **Review folding:**
  - `git.review_comment` updates the task's `git.reviewed` event with the same `data.review_id`: `comments += 1`, and
    `first = {file, line, excerpt, url}` when unset.
  - When there is no such event yet, it creates one with verdict `commented`, actor and `comments: 1`.
  - A later `git.reviewed` with that id fills in the verdict, excerpt, url and actor.
  - Assign a new dict to `data` so the JSONB change is saved.

- [ ] **Step 1: Write the failing tests:**
  - `test_push_to_the_task_branch_is_recorded_as_a_person`: no agent run, so the actor is `{"kind": "person",
    "name": "mo", "login": "mo"}`, the host is `"github"` and `commits == 1`. A push to `main` records nothing.
  - `test_push_and_pr_opened_during_an_agent_run_are_the_agent`: an `AgentRun` on the task with status `running`.
    Then that run finished 4 minutes ago, which still gives the agent. Then finished 6 minutes ago, which gives a
    person.
  - `test_pr_opened_links_the_pr_so_comments_and_merge_find_the_task`: opened from `megoo/PAY-1-x`, then an
    `issue_comment` with no branch is recorded on PAY-1, then a merge gives `git.pr_merged` with actor `mo`.
  - `test_a_tracked_pr_is_found_without_a_branch`: a `TaskPullRequest` row only, then a comment is recorded.
  - `test_push_says_the_pr_was_updated`: after opened, a push to the same branch has `pr.number == 1`.
  - `test_a_line_comment_before_its_review_makes_one_entry`: comment (review 9), comment (review 9), review 9
    `changes_requested` gives exactly one `git.reviewed` with `verdict == "changes_requested"`, `comments == 2` and
    `first.file == "src/a.py"`.
  - `test_a_branch_of_a_project_without_this_repository_is_ignored`: `megoo/OTHER-1-x` where project OTHER has no
    `acme/pay` repository records nothing on OTHER-1.
  - `test_a_delivery_naming_another_repository_is_ignored`: through `/repos/{repo.id}`, a payload for `acme/web`
    records nothing.
  - `test_a_repeated_delivery_records_once`: the same `X-GitHub-Delivery` twice gives one entry.
- [ ] **Step 2: Run** `uv run pytest -q tests/git/test_activity.py`. Expected: it fails, with no `git.*` events
  recorded (or an import error for `app.git.activity`).
- [ ] **Step 3: Implement.** Add the model and migration (run `alembic upgrade head` on `megoo_migrate`), then
  `activity.py`, then the `_handle` call.
- [ ] **Step 4: Run** `uv run pytest -q tests/git`. Expected: all pass (the earlier git tests too).
- [ ] **Step 5: Commit** `feat(git): pushes, pull requests, comments and reviews on the task's Activity`.

### Task 3: Checks, and one line per merge or close

**Files:**
- Modify: `backend/app/git/service.py` (`apply_status`).
- Modify: `backend/app/tasks/activity.py` (`activity_items`).
- Test: `backend/tests/git/test_activity.py`, and `backend/tests/tasks/test_activity*.py` (whichever holds the
  feed's tests; add there if one exists, otherwise to the git test file).

**Interfaces:**
- Consumes: the `pr` and `host` data shape from Task 2.
- **Checks:** in `apply_status`, when `status.checks` changes to `success` or `failure` and `status.head_sha` is
  set, record `git.checks` through `record_workflow_event`:
  - data: `{host, actor: None, pr: {number, url}, result: "passed"|"failed", head_sha}`;
  - only when no `git.checks` event with the same `head_sha` and `result` exists on the task.
- **Failing check names:** the provider read (`PrStatus`) doesn't give them, so they aren't shown. The spec allows
  this ("where the host gives them"), and a count is optional.
- **`activity_items`:**
  - Also leave out `pr.status`.
  - Leave out `pr.merged` and `pr.closed` events where the same task has a `git.pr_merged` or `git.pr_closed` event
    whose `data->'pr'->>'url'` equals their `data->>'url'`. Compare with trailing `/` stripped. Use a NOT EXISTS
    subquery, so paging stays correct.

- [ ] **Step 1: Write the failing tests:**
  - `test_checks_record_once_per_head_and_result`: apply `pending`, `success` (sha a), `success` (sha a again),
    `failure` (sha b), which gives exactly two `git.checks`.
  - `test_pr_status_is_not_in_activity`.
  - `test_one_merge_line_whichever_comes_first`:
    - poll then webhook: `pr.merged` then `git.pr_merged` gives only `git.pr_merged` in `/api/tasks/{key}/activity`;
    - webhook then poll: the same result;
    - poll only: `pr.merged` stays.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q tests/git tests/tasks`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(git): checks results on the task, and a merge or close shown once`.

### Task 4: Show them in the Activity thread

**Files:**
- Create: `frontend/src/lib/gitActivity.ts`.
- Modify: `frontend/src/components/task/ActivityThread.tsx`. Give `git.*` kinds, `pr.merged` and `pr.closed` their
  own row component `GitEventRow`.
- Test: `frontend/src/lib/__tests__/gitActivity.test.ts`, and `frontend/src/components/task/__tests__/` (add
  `GitActivity.test.tsx`).

**Interfaces:**
- Consumes: the stored data shape (Tasks 2–3).
- Produces:
  ```ts
  export type GitLine = {
    icon: "push" | "opened" | "comment" | "approved" | "changes" | "reviewed" | "checks-passed" | "checks-failed" | "merged" | "closed";
    lead: string | null;      // actor name; null for standalone lines (checks, a nameless merge/close)
    agent: boolean;           // shows the "agent" tag
    text: string;             // the Global Constraints wording
    host: string | null;      // "GitHub" | "GitLab" | "Gitea"
    href: string | null;      // the PR or comment page (http/https only)
    quote: string | null;     // excerpt, plain text
    where: string | null;     // "src/a.py:88"
    detail: string | null;    // "2 comments" for a review; the host login as a title when the actor is an agent
  };
  export function describeGitEvent(kind: string, data: Record<string, unknown>): GitLine | null;
  ```
- **Lucide icons:**
  - `GitCommitHorizontal` (push), `GitPullRequestArrow` (opened), `MessageSquare` (comment);
  - `CircleCheck` (approved, checks passed), `CircleX` (changes requested, checks failed);
  - `GitMerge` (merged), `GitPullRequestClosed` (closed).
- **Nameless merges and closes:** `pr.merged` gives "PR #n merged" and `pr.closed` gives "PR #n closed without
  merging", with the number parsed from `data.url`. If there is no number, it says "The pull request".
- **Layout:** the quote is a muted block under the line, never rendered as Markdown. The row's text uses
  `min-w-0 break-words`, so long branch names wrap.

- [ ] **Step 1: Write the failing tests:**
  - `gitActivity.test.ts`: for each kind, `describeGitEvent` returns the exact text from Global Constraints. Also:
    - an agent actor sets `agent: true`;
    - a `javascript:` URL gives `href: null`;
    - an unknown `git.x` gives `null`.
  - `GitActivity.test.tsx`: render `ActivityThread` with one item of each kind. Check that:
    - each row shows its lead, text and host chip;
    - the review row shows `src/a.py:88` and "2 comments";
    - an excerpt of `<script>alert(1)</script>` shows as literal text;
    - the PR link has `target="_blank"` and `rel` with `noopener`.
- [ ] **Step 2: Run** `npx vitest run src/lib/__tests__/gitActivity.test.ts src/components/task/__tests__/GitActivity.test.tsx`.
  Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them, then** `npx vitest run`, `npx tsc --noEmit` and `npx eslint src`. Expected: all pass,
  and the existing ActivityThread tests are unchanged.
- [ ] **Step 5: Commit** `feat(git): the task's Activity shows pushes, pull requests, reviews and checks`.

### Task 5: End to end

**Files:**
- Modify: `frontend/e2e/helpers/fakeGit.ts`. Add
  `delivery(event: string, payload: object, secret: string): { body; headers }`, which signs the payload and sets
  `X-GitHub-Event` and a unique `X-GitHub-Delivery`. Keep `pullRequestDelivery`, now sending `merged: true`,
  `sender.login: "mo"`, `html_url` and `head.ref`.
- Modify: `frontend/e2e/git.spec.ts`.

**Steps in `git.spec.ts`:** after step 3 ("PR open · checks pending"), and before the merge, through the
repository's own address:
- a `push` of 1 commit to `refs/heads/megoo/GIT-1`, pusher `admin-gh`;
- `pull_request` `opened` #1, head `megoo/GIT-1`, base `main`, sender `admin-gh`;
- `pull_request_review` `submitted`, state `changes_requested`, body "Add a back-off", sender `rev`.

Then the task drawer's Activity shows:
- "pushed 1 commit to megoo/GIT-1" and "opened PR #1", both led by the agent name with its "agent" tag. The finish
  run has just ended, within 5 minutes.
- "rev requested changes on PR #1" with "Add a back-off".

After step 4's merge delivery, Activity shows "mo merged PR #1" exactly once, and no "PR #1 merged" line. Then, at a
280 px viewport, the drawer shows no sideways scroll: `document.documentElement.scrollWidth <= 281`.

- [ ] **Step 1: Write the new e2e steps.**
- [ ] **Step 2: Run** the git spec on a fresh megoo-e2e stack. Expected: PASS. If it fails, debug the cause, never
  the assertion.
- [ ] **Step 3: Run** the full backend suite (one run at a time), the web suite, tsc and eslint, and the whole e2e
  suite on a fresh stack. Expected: all green.
- [ ] **Step 4: Commit** `test(e2e): the task's Activity follows its pull request`.
