# Changes requested on the pull request send the task back (piece 3 of 4)

Status: the owner said "continue" instead of answering questions, as with piece 2, which I read as skipping them.
This design follows what they agreed earlier in the session and the mockup they saw
(`.superpowers/brainstorm/1176-1793711513/content/pr-loop.html`, git-ignored).

- What the owner asked for: "when human or agent comment on PR that code needs fixing etc... and reject the merge,
  make the task start again and agent fixes the issue and resubmit PR again with updates for review."
- What was agreed: "a changes requested review, or a comment starting with `/fix`, sends the task back to Build.
  The agent fixes, pushes, and the PR updates. At most 3 rounds, then it asks the human. A project checkbox turns it
  on."
- Calls made without the owner are marked **(my call)**.
- Pieces 1 (per-repository webhooks) and 2 (pull request events on the task's Activity) are merged to develop at
  `b7cb630`.

## Why

Today, once the agent's pull request is open and the task waits for the merge, MegooColab can only be told "merged".
When a reviewer asks for changes on GitHub or GitLab, someone has to notice and start the agent again by hand, and
explain what to fix. Piece 2 already records each review and comment on the task. This piece acts on the ones that
ask for a fix.

## Goals

1. **A project checkbox turns it on.** In Project › Settings › Workflow:
   - The checkbox reads "Send the task back when changes are requested on its pull request". It is off by default
     for every project, existing and new **(my call: opt-in, as it starts agent runs)**.
   - Its help text: "A 'changes requested' review, or a comment starting with /fix, sends the task back to its agent.
     The agent fixes the code and pushes to the same pull request. At most 3 rounds, then it asks you. On GitLab, use
     a /fix comment."
2. **What sends it back.** The project's checkbox must be on, and the workflow must be waiting for the merge
   (`waiting_human`, needs `human_code_review`). Then either of these sends it back:
   - a review with the verdict **changes requested** on the task's pull request, from a person or an agent (GitHub,
     Gitea);
   - a comment on the task's pull request whose text **starts with `/fix`** (case-insensitive, after leading spaces).
     The rest of the comment is the request (GitHub, GitLab, Gitea).

   Anything else stays as an Activity entry only: approvals, other comments, and events while a fix is already
   running or the task is finished.
3. **Who may send it back.**
   - On GitHub, only accounts with write access: `author_association` of OWNER, MEMBER or COLLABORATOR. Others' reviews
     and `/fix` comments show in Activity and do nothing **(my call: on a public repository a stranger must not be able
     to start agent runs)**.
   - GitLab and Gitea payloads don't say this, so anyone who can comment on the pull request counts. The checkbox's
     help says so.
4. **Sent back:**
   - The task's stage shows **Build** again, and its card moves as on any stage change.
   - Activity gets one line: "Sent back to its agent: changes requested on PR #n by rev (round 2 of 3)". For `/fix` it
     reads "… /fix on PR #n by mo …".
   - The task's agent gets a fix run. It works in the task's worktree on the task's branch, with:
     - the task, its design and plan, the pull request's address and branch;
     - what was asked: the review summary or `/fix` text, plus the first line comment's place and words, from the
       recorded event;
     - an instruction to read every review comment and line comment itself with the host's command-line tool
       (`gh pr view <url> --comments`, `glab mr view <n> --comments`, `tea`), since only short excerpts are stored.

     The fix run:
     - fixes the code and runs the tests;
     - commits and **pushes to the same branch**, with no force-push and no new pull request;
     - reports what it changed, and whether the tests passed.
   - The pull request updates on the host. Piece 2 shows the push as "pushed N commits … · PR #n updated".
5. **After the fix:**
   - **Tests passed and pushed:** the stage shows **Done** again, and the workflow waits for the merge
     (`human_code_review`) as before. Activity says "Fixed and pushed to PR #n (round 2 of 3)", with the agent's summary.
     A new review can send it back again.
   - **Tests failed, nothing reported, or the run failed:** the workflow asks the human (escalation
     `pr_fix_incomplete`), the same way a Finish run that ends unfinished does.
6. **At most 3 rounds per pull request.** A fourth trigger doesn't start a run. The workflow asks the human
   (escalation `pr_fix_rounds_exhausted`, "Changes were requested 4 times on PR #n").
   - **Retry:** one more fix round.
   - **Accept:** go back to waiting for the merge, without fixing.
   - **Pause:** as for any escalation.

   The count is stored on the workflow, and a new pull request starts it again at 0.
7. **The workflow panel while it's sent back** follows the mockup:
   - "Changes requested on PR #n by rev · laptop-claude is fixing them · round 2 of 3";
   - a **"Don't send back"** button. It cancels the fix run and returns the workflow to waiting for the merge. The
     round still counts **(my call)**.

## Non-goals

- A "Request changes" button inside MegooColab. Only the host's reviews and comments send a task back.
- Reopening a task that is already finished. That includes a project without "Require human code review", whose
  task is Done as soon as the PR opens. Piece 4 replaces that setting.
- An agent reviewing the PR. That is piece 4. When it requests changes, this piece sends the task back like a
  person's review would.
- Fetching full review bodies through MegooColab's token. The agent reads them with its own CLI.
- GitLab's "changes requested" signal. Its webhook doesn't carry one, so GitLab uses `/fix`.

## Anti-goals

- **A loop:**
  - The agent's own push or comments must never trigger a send-back.
  - A review that arrives during a fix doesn't start a second run.
- **A send-back without its trigger:** neither a missing checkbox nor an approval may start a fix run.
- **A new pull request** for a fix, or a force-push.
- **A stranger's comment on a public GitHub repository** starting agent runs.

## Constraints

- **Webhook-driven.** Send-backs come from the deliveries piece 2 records; the poll doesn't send back.
- **Atomic with its Activity entry.** The trigger is checked in the same transaction as the event's Activity entry,
  under the task and workflow locks.
- **Never fails the delivery.** As in piece 2, it runs inside the delivery's savepoint, so a failure is logged and
  the delivery still succeeds.
- **The fix run dispatches after commit,** as other engine runs do.
- **The fix run's instructions** live in the methodology texts as a new role, so admins can edit them like the
  others.

## Testing

- **Backend:**
  - a changes-requested review sends back only with the checkbox on and the workflow waiting for the merge;
  - `/fix` sends back, while other comments don't;
  - GitHub's `author_association` gate;
  - a trigger during a fix does nothing;
  - the 4th trigger escalates, and Retry and Accept behave as described;
  - the fix report with tests passed returns to waiting, and an incomplete one escalates;
  - "Don't send back" cancels the run;
  - the round count starts again for a new pull request.
- **Frontend:**
  - the checkbox and its help text;
  - the panel's sent-back line and button;
  - the Activity lines for sent back and fixed;
  - the escalation reason text.
- **e2e:** the git end-to-end test adds:
  - the checkbox turned on;
  - a changes-requested review from `rev`;
  - the fake agent's fix run pushing and reporting;
  - Activity showing "Sent back…" then "Fixed and pushed…";
  - the panel waiting for the merge again, then the existing merge finishing the task.

## Left to the builder

- The fix run's role name and methodology key (`pr_fix` is suggested).
- How the fix report reaches MegooColab: a new tool for the agent, or the existing finish report with a new outcome.
  It must carry a summary and whether the tests passed.
- How the stage shows Build while fixing without the build stage's step logic acting on it.
- The exact Activity event kinds (`pr.sent_back` and `pr.fix_pushed` are suggested).
