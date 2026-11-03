# Pull request and branch events on the task's Activity (piece 2 of 4)

Status: the owner chose to skip the questions ("skip questions"). This design follows what they agreed earlier in
the session for the four pieces, and the Activity mockup they saw (`.superpowers/brainstorm/1176-1793711513/content/
pr-loop.html`, "On the task: its Activity follows the PR"; git-ignored). Calls made without them are marked
**(my call)**. Piece 1 (connections, picker, per-repository webhooks) is merged to develop at `cc15738`.

## Why

The owner wants to see on a task what people and agents do on its pull request and branch, as it happens: who
pushed, who opened the PR, who commented or reviewed, whether checks passed, and who merged or closed it. Today a
webhook delivery only triggers a re-read of the PR's state. The task records a bare `pr.status` change, which shows
as the raw text "Someone pr.status". Comments, reviews, pushes and the people behind them are thrown away.

Pieces 3 and 4 act on these events. Piece 3 sends the task back when changes are requested; piece 4 has an agent
review and merge. Both need them recorded on the task first.

## Goals

1. **The task's Activity follows its PR and branch,** as entries in the same thread as comments and workflow events.
   One entry per:
   - **push** to the task's branch: who pushed, how many commits, and the first commit's title. When the branch has
     an open PR it adds "PR #n updated". There is no separate "PR updated" entry **(my call)**.
   - **PR opened:** number, title, `head → base`, linked to the PR.
   - **comment** on the PR, the conversation or a line: an excerpt of up to 280 characters, the `file:line` for a
     line comment, and a link to the comment.
   - **review submitted:** the verdict (approved, changes requested, commented) and an excerpt of its summary.
     - Its line comments are folded into the one entry, never shown on their own: the first one's `file:line` and
       excerpt, and "N comments".
   - **checks finished** on the PR's head commit: passed or failed, and the failing checks' names where the host
     gives them (up to 3). There is one entry per head commit and result, never one per check run.
   - **merged** or **closed without merging:** who did it.
2. **Each entry names who acted and where:**
   - The actor is either **an agent**, shown by its MegooColab name with an "agent" tag, or **a person**, shown by
     the name the host gives (display name, else login).
   - The host is "GitHub", "GitLab" or "Gitea", from the repository's connection.
   - The time is when MegooColab received the event.
3. **Nothing is noisy or doubled:**
   - one entry per push, not per commit;
   - one per review, not per line comment;
   - one per check result, not per check run;
   - a repeated delivery is already ignored (piece 1).
   - The bare `pr.status` entries stop showing in Activity. They stay stored. **(my call)**
   - The existing `pr.merged` and `pr.closed` entries currently show as raw kinds. They are shown properly, and a
     merge or close appears as a single line, see "Merged and closed" below.
4. **It arrives live:** a new entry appears on an open task without reloading, as other Activity entries do.

## How events reach a task

Events come from the repository's own webhook (piece 1), or from the connection's shared address while one is still
in use.

- **The task's branch** is how pushes and new PRs find their task:
  - The runner names a task's branches `megoo/<KEY>-<slug>`, and back-merge branches `megoo/<KEY>-<slug>-to-<branch>`.
  - A push to `refs/heads/megoo/<KEY>…`, or a PR whose head branch is `megoo/<KEY>…`, belongs to task `<KEY>`.
    That task must be in a project that has this repository.
  - This works before MegooColab tracks the PR, since the webhook for "opened" usually arrives before the agent's
    finish report.
- **A PR** is how comments, reviews, checks, merges and closes find their task:
  - Its URL is tracked for the task (`TaskPullRequest`), or MegooColab has seen it opened from the task's branch.
  - The second case needs a lookup from (repository, PR number) to the task, kept when the opened event is
    recorded. How it is stored is up to the builder.
- **Everything else is ignored:**
  - pushes to other branches (main included);
  - branch deletions;
  - PRs of other branches;
  - edited or deleted comments.
- **Checks** are recorded from the PR's tracked state when its combined checks settle to passed or failed for a head
  commit: the existing refresh after a delivery, and the 2-minute poll. They are not taken from each check-run
  delivery **(my call: one place already computes the combined result)**. Failing names only where the provider read
  gives them. A count such as "4/4" is optional.
- **Without a working webhook,** only what the poll sees shows: checks, merged and closed, with no names. That is
  acceptable, and the repository's webhook status (piece 1) already says why.

## Who acted: agent or person

Agents push and open PRs with the developer's own git credentials (`finish.md`), so the host reports the person's
account. MegooColab decides which agent acted from its own records:

- **A push or a PR opened** on the task's branch belongs to **the agent of an agent run on this task** that was
  running when the event arrived, or had finished within the last 5 minutes. With several, it is the most recent.
- **Otherwise it is a person,** shown by the host's name. That includes comments and reviews in this piece. **(my
  call)**
  - Agents don't comment or review on the host until pieces 3 and 4, and those pieces will mark what they post.
- **Known limit:** a person pushing to the task's branch while its agent is working is shown as the agent. This is
  accepted. The entry still shows the host account in its tooltip or detail, so the truth is one hover away.
- There is no mapping of host accounts to MegooColab users in this piece. The person is the host's name. **(my call)**

## What an entry looks like

This follows the mockup the owner saw:

- **Lead:** the actor's name, with an "agent" tag for agents.
- **Text:** the event in words, for example:
  - "pushed 2 commits to `megoo/PAY-7-retries` · PR #42 updated"
  - "opened PR #42 · megoo/PAY-7-retries → main"
  - "requested changes on PR #42"
  - "commented on PR #42"
  - "Checks passed on PR #42"
  - "merged PR #42"
- **Host chip:** "GitHub", "GitLab" or "Gitea".
- **Icon per kind:** push, PR, comment, review (approved, changes, commented), checks (passed or failed), merged,
  closed.
- **Below the text:** the excerpt, quoted and muted, with the `file:line` of a line comment.
- **Links:** the PR number and the excerpt open the host's page in a new tab.
- **Phone width:** entries fit a 280 px screen. Long branch names wrap or truncate and never scroll sideways.

## Merged and closed

- When the webhook says who merged or closed the PR, the entry reads "Mo merged PR #42".
- The existing workflow consequence stays its own entry ("Moved to Done by the workflow", the escalation on a close).
- The old nameless `pr.merged` and `pr.closed` lines show only when no named merge or close entry exists for that PR,
  that is when the poll saw it first. Either way the reader sees one line per merge or close, plus the workflow's
  line.

## Storage

- **Entries:** `TaskEvent` rows with `git.*` kinds. Their `data` carries:
  - `host`;
  - `actor`: `{ kind: "agent" | "person", agent_id?, name, login? }`;
  - `pr`: number and URL;
  - per kind, the branch, commit count and first title, the excerpt, `file:line`, the verdict, the review id, and
    the comment count.
  - `actor_user_id` stays null.
- **Live updates:** the same live update as workflow events (`task.updated`).
- **Not stored:** raw payloads.
- **Size:** excerpts are capped at 280 characters, and only up to 3 commit titles or failing check names are kept.

## Non-goals

- Acting on events: sending back on "changes requested" or `/fix` is piece 3, and agent review and merge is piece 4.
- Notifications, emails or the board badge changing because of these events. The badge already follows the PR state.
- Chats. Their PRs aren't tracked as a task's are today.
- Linking host accounts to MegooColab users, or showing avatars.
- Full comment bodies or threads inside MegooColab. The excerpt links out.
- Back-filling events from before this ships.

## Anti-goals (a failure even if it works)

- An Activity feed flooded by CI: an entry per check run or status context.
- The same event shown twice, for example a push and a "PR updated", or a merge from both the webhook and the poll.
- A secret, token or a full payload stored or shown.
- Entries that scroll sideways on a phone.

## Testing

- **Backend:** for GitHub, GitLab and Gitea payloads, each kind is mapped to the right task:
  - by branch, by tracked PR, and by the PR seen opened;
  - ignored cases: other branches, deletions, edits.
- **Backend, actor:** an agent during a run and within 5 minutes after it, a person otherwise.
- **Backend, folding:** line comments fold into the review, and checks give one entry per head commit and result.
- **Backend, merges:** one line per merge or close with the webhook first, and with the poll first.
- **Backend, repeats:** a repeated delivery adds nothing.
- **Frontend:** each kind renders with its actor, agent tag, host chip, excerpt and links. `pr.status` is hidden.
- **e2e:** the existing git e2e test adds these steps, with the fake host sending the deliveries:
  - a push to the task branch;
  - PR opened, with the agent shown as the actor;
  - a review requesting changes, from a person;
  - a merge by a person.

  The task's Activity shows each line. The phone-width e2e check also covers a task with these entries.

## Left to the builder

- How the (repository, PR number) → task lookup is kept.
- The exact icon set.
- Whether checks show a count.
- The parsing helpers per provider. This is where the providers' payload differences live:
  - GitLab review verdicts come from merge request `approved` and `unapproved` actions and notes;
  - Gitea uses its review event names.
