# A merged pull request finishes the round, even when the token can't read everything

## Why

A project can have an agent review and merge the pull request that a task's or chat's round opens
(`finish_pr_review = agent`). When the agent merges, the round should finish by itself. On a real install
(OdooShield, PR #1, task OS-1), it didn't, and the dashboard kept showing **Code review · Review**, as if a person
still had to look.

What happened:

- MegooColab takes a pull request's state only from the host's API (`service.refresh_pr` → `providers.fetch_pr`).
  A webhook only triggers a read.
- On GitHub one read makes four calls: the PR, its commit's combined status, its commit's check runs and its
  reviews (`providers._github`). A 403 on any one raises `forbidden` and the whole read fails.
- The "Personal Github" token got 403 on every read: 28 failures, now one try an hour (`back_off`). The likely
  cause is that it lacks **Commit statuses: read** and **Checks: read**. The connection form's hint
  (`frontend/src/lib/git.ts`, `TOKEN_HELP.github`) doesn't ask for those; `docs/install.md` does.
- The merge was never stored, so `settle_done` never finished the round. The workflow sat in
  `waiting_human / human_code_review`.
- Nothing in the UI said the reads were failing.
- Needs you lists every `waiting_human` row with `needs` set (`dashboard/needs.py`, `_workflow_waits_query`), so a
  round waiting for MegooColab to see the agent's merge shows as a person's code review.
- The Workflow panel's "Approve the PR" label (`lib/workflow.ts`) and the chat header's "in code review" say the
  same.

Tasks and chats share all of this code, so both are affected the same way.

## Goals

1. A merge is seen even when the token can't read checks, statuses or reviews.
2. The connection form asks for every permission a read needs.
3. When reading a pull request fails, people can see that it fails and why, in words.
4. A round waiting on an agent's merge isn't shown as a person's job, unless confirming the merge fails; then one
   clear item asks a person, with a way to finish it.
5. All of the above holds for tasks and chats alike, and for human-reviewed pull requests where it applies.

## Non-goals

- No change to how the agent reviews or merges.
- No new notification kinds. An escalation already notifies (`engine.escalate` → `wait_for`), and that's enough.
- No trusting the agent's own "merged" report to finish the round without the host or a person confirming it.
  (MegooColab's rule stays: the host's API or a person says it's merged.)
- No change to the poll's cadence or backoff timings.

## Anti-goals

- A person is told "Review" or "Code review" for a pull request the agent is handling.
- A failing read stays silent.
- A limited token that can read the PR still blocks a merge from being seen.
- A round waiting on the agent stays stuck with no way out for a person.

## 1. Tolerant reads

In `providers._github` and `providers._gitea`, the pull request call stays required: if it fails, the read fails
as today.

The extras (the commit's combined status, its check runs, the reviews) become optional:

- A 403 (`forbidden`, not rate limited) or a 404 (`not_found`) on an extra means that extra is unknown. It
  doesn't fail the read.
- Other errors on an extra (`unauthorized`, `rate_limited`, `unreachable`, `bad_response`) still fail the read,
  as today.
- `checks` becomes `unknown` when either checks call was refused. If one of the two succeeded, its result is
  not used on its own: the combined value is `unknown`.
- `review` becomes `unknown` when the reviews call was refused.
- `unknown` is a new allowed value of `TaskPullRequest.checks` and `.review` (both `String(20)`, so no schema
  change). Update the model comments, `PullRequestOut`, and the frontend maps:
  - `CHECKS.unknown = "checks unknown"`;
  - `REVIEW.unknown = "review unknown"`.
- `_record_checks` already ignores anything but success or failure, so `unknown` writes no Activity line.
- A read with an unknown extra still counts as a success: `failures = 0`, the next check in `POLL_SECONDS`.
  It also stores what was missing (see 3), so people can tell why the checks are unknown.

GitLab is unchanged: its pipeline comes with the merge request, and approvals are already optional.

**Done when:** a token that can read the PR but gets 403 on statuses, check runs or reviews still records
`merged`, and the waiting round finishes.

## 2. The token hint

`TOKEN_HELP.github` asks for what `docs/install.md` asks for: **Contents, Metadata, Pull requests, Commit
statuses and Checks (read)**, or a classic token with repo. The optional parts (webhooks; review and merge)
stay as they are. Check the Gitea hint against what `_gitea` calls (PR, commit status, reviews) and fix it the
same way if it falls short.

## 3. Read failures are visible

### What is stored

- A failed read already stores `TaskPullRequest.error` (the provider's code) and `failures`.
- A partial read (1 above) also stores which extras the token couldn't read. The builder picks how, for example
  a short code in a new nullable column, `limited`, such as `"checks"`, `"review"` or `"checks,review"`. Don't
  put it in `error`, because `error` means "the read failed". A full read clears it.

### What is shown

Expose to the frontend:

- `PullRequestOut.error`: the code, or null. Leave out `branch_mismatch`: it has its own meaning, and isn't a
  read failure.
- `PullRequestOut.limited`.

Where they show:

- **The PR badge** (`PullRequestBadge`, used on task pages, cards and chats). On a failure, it reads
  "PR · can't read" in the muted pink tone, with the full reason in its `title` and accessible name.
- **The Workflow panel**, under the PR, one line: "MegooColab can't read this pull request: <reason>. It tries
  again at <time>."
  - For a partial read it says instead: "Checks unknown: the token can't read commit statuses or checks."
  - For reviews: "Review unknown: the token can't read reviews."
- **Settings › Repositories.** Beside the webhook status, each repository shows its most recent pull request
  read problem, if the most recent read of any tracked PR for that repository in this project failed or was
  partial. For example: "Can't read pull requests: GitHub refused the token (forbidden). Give it Pull requests,
  Commit statuses and Checks (read)." Work it out at query time, from the tracked rows whose URL matches the
  repository. No new table.

### The reasons in words

One frontend map (`lib/git.ts`), with the host's name filled in:

| Code | Text |
|---|---|
| `forbidden` | GitHub refused the token (forbidden). It needs Pull requests, Commit statuses and Checks (read). |
| `unauthorized` | GitHub rejected the token. It may have expired or been revoked. |
| `not_found` | The token can't see this repository or pull request. |
| `rate_limited` | GitHub is limiting requests. MegooColab will try again. |
| `unreachable` | GitHub couldn't be reached. |
| `bad_token` | The saved token can't be read. Save it again in Settings › Git. |
| `url_mismatch` | The pull request isn't on this connection's address. |
| `bad_response` / `error` | GitHub sent something MegooColab didn't understand. |

The `forbidden` permission hint is for GitHub. For GitLab and Gitea, use the matching words from their token
hints.

## 4. An agent-handled merge isn't a person's job

### A new wait: confirming the merge

When the agent review run ends and the workflow comes to rest waiting for the merge (`_handle_pr_review` in
`git/agent_review.py`, today `wait_for(Needs.human_code_review, notify=False)`), it waits on a new kind,
**`Needs.merge_confirmation`**. *My call:* a new `Needs` value; `needs` is `String(30)`, so there is no migration
for the column.

**Only that path** uses it, and only when MegooColab can confirm the merge by itself. *My call:* in these cases
the round rests on `human_code_review` instead, as today, because a person has to act or confirm:

- a back-merge pull request exists (`wf.back_merge_pr_url`): the agent reviews and merges only the main one, and a
  person merges the back-merge one;
- the main pull request is untracked (`connection_id` is None), so MegooColab never reads it;
- its row is `branch_mismatch`, so `settle_done` never acts on it.

The rest is unchanged:

- A person taking over (`_accept_waits_for_the_merge`) still waits on `human_code_review`: from then on it's a
  person's job.
- Human-review mode is unchanged.
- Agent review "approved but not merged" and "no verdict" escalate as today.

**In every logic check, `merge_confirmation` behaves like `human_code_review`.** *My call:* only Needs you, the
waiting counts, notifications and the labels tell them apart. The builder finds the checks with a search for
`human_code_review`. Two of them are:

- ending a chat leaves the round alone (`chats/service.py`, the end-chat pause);
- resuming a paused round restores `merge_confirmation` if that was the wait it paused from
  (`engine._pending_need`), with `waiting_since` reset.

### What reads the new wait

| Where | What changes |
|---|---|
| `settle_done` | Acts on `merge_confirmation` exactly as on `human_code_review`: closed escalates, all merged finishes. |
| `approve_human_review` (**Mark merged**) | Accepts `merge_confirmation` too, so a person can still finish it. |
| Needs you (`_workflow_waits_query`) | Leaves `merge_confirmation` out. So do the counts that use the same query, and the chat waiting counts (`chats/service.py` `waiting_count`, frontend `WAITING`). |
| Chat state | `NEEDS_STATE[merge_confirmation]` → a new chat state `merging`, shown "merging · PR #n" (or "merging"). It isn't a waiting state. |
| Workflow panel | Label "Agent merged · confirming". A line: "The agent merged the pull request. MegooColab finishes the round when GitHub shows the merge." **Mark merged** stays, as a secondary button, for anyone who can decide. |
| Workflow labels | Any other place that maps `needs` to text (`lib/workflow.ts`, the task card or board badges, API types) gets `merge_confirmation`. The builder finds these with a search for `human_code_review`. |

### When confirmation fails

A new escalation reason, **`merge_not_confirmed`**. Raise it from the PR read path (`refresh_pr`, or right
after `apply_status`), only while the workflow waits on `merge_confirmation`:

- **A read fails with a lasting error** (`forbidden`, `unauthorized`, `not_found`, `bad_token`,
  `url_mismatch`): escalate on the first such failure.
- **A read fails with a passing error** (`rate_limited`, `unreachable`, `bad_response`, `error`): escalate after 3
  failures in a row since the wait began (about 14 minutes with the current backoff). *My call:* count only the
  failures since `waiting_since`, not the row's lifetime `failures`, so a migrated or long-failing row doesn't
  escalate on an old count.
- **The read works, but the PR is still `open`** 10 minutes after the wait began (`waiting_since`): escalate.
  The agent said it merged, but the host disagrees.

What the escalation does:

- **It records the cause** in the `workflow.escalated` event data: the error code, or `still_open`.
  `escalation_reason` stays the plain `merge_not_confirmed`, because it is the lookup key for the handlers and
  texts.
- **The text** (`ESCALATION_REASON_TEXT`): "The agent merged the pull request, but MegooColab couldn't confirm
  it." The panel adds the current reason. *My call:* it works this out live from `PullRequestOut.error` and
  `state`: the reason from 3, or "GitHub still shows it open." Then there's no new column, and the line follows
  later reads.
- **Retry** reads the pull request again. *My call:* it goes back to `merge_confirmation` with `waiting_since`
  reset, then `queue_refresh`. Add a `RETRY_HANDLERS["merge_not_confirmed"]` entry, so Retry never reruns the
  reviewer. Pause stays as for any escalation.
- **The way out:** `merge_not_confirmed` goes into `ACCEPTABLE_REASONS`, with an accept handler that finishes the
  round like **Mark merged** (same event and audit as `approve_human_review`). The button reads
  **Mark merged**, not "Accept".
- **It clears itself:** reads continue (the row is still `open`, so the poll keeps trying with backoff). If a
  later read sees `merged`, `settle_done` also acts on a workflow escalated with `merge_not_confirmed`, finishing
  the round and clearing the escalation. If it sees `closed`, it escalates `pr_closed` as today.

### Rounds already waiting

On upgrade, a data migration moves today's stuck rounds to the new wait. It touches the workflows that:

- are `waiting_human / human_code_review`, at stage `done`, with `finish_pr_review = 'agent'`;
- have no back-merge pull request, and a tracked main row that isn't `branch_mismatch`;
- have a latest `pr.agent_reviewed` event with `merged: true`;
- have no later `workflow.escalated` event (one would mean a person took over).

Those rows move to `merge_confirmation`. All other rows stay as they are. Run the migration against
`megoo_migrate` only.

## Tests

Backend (pytest):

- **Provider:**
  - a 403 on status, check runs or reviews still returns the PR state, with `unknown`, for GitHub and Gitea;
  - a 403 on the PR call still raises `forbidden`;
  - a 401 on an extra still raises.
- **Service:** a partial read stores `limited`, clears `failures`, and a `merged` partial read finishes a
  waiting round.
- **Agent review:**
  - a merged review rests on `merge_confirmation`, not in Needs you, and with no notification;
  - a person's takeover still rests on `human_code_review` and is in Needs you.
- **Escalation:**
  - a lasting error escalates `merge_not_confirmed` on the first failure; a passing one on the third;
  - still open after 10 minutes escalates;
  - a later merged read finishes the escalated round;
  - accept finishes it;
  - Retry reads again and reruns no agent.
- **Who waits on what:** a back-merge PR, an untracked PR or a branch mismatch rests on `human_code_review`.
- **Chats and pauses:** ending a chat leaves a `merge_confirmation` round alone, and a resume restores it.
- **Mark merged:** it works on `merge_confirmation`.
- **Needs you:** it leaves `merge_confirmation` out, for a task and for a chat.
- **Migration:** it moves exactly the qualifying rows.

Frontend (vitest):

- the badge's error and unknown texts;
- the reason map;
- the Workflow panel's confirming and escalated states;
- the chat state text;
- the token hint.

e2e: one spec, on the e2e stack with a stubbed host. If the stack can't stub GitHub, the builder says so instead.
It checks two things:

- an agent-merged round shows "merging" in the chat header and no Needs you item;
- after a forced read failure, the round shows a Mark merged escalation.

## Left to the builder

- How `limited` is stored (column name and format).
- The exact visual treatment of the badge and panel lines, within the existing components and tones.
- Where in the read path the escalation check sits, as long as it runs once per read under the workflow lock.
- Release notes and the version bump wait for "release".
