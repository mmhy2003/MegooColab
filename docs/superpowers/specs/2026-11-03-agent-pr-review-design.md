# Pull request review: None, Human or Agent (piece 4 of 4)

Status: approved in conversation. The owner answered "mine" (the agent reviews and merges as the owner's own account)
and "go" to the played-back design. Calls I made are marked **(my call)**.

- Earlier agreements in the session:
  - "the user either choose human or agent review"
  - "the agent merge it"
  - the reviewer is "the task's own agent in a fresh session by default, or a chosen agent"
  - existing projects map Off → None and On → Human
  - the PR-loop mockup (`.superpowers/brainstorm/1176-1793711513/content/pr-loop.html`, git-ignored)
- Pieces 1–3 are merged to develop at `6e957b3`.

## Why

Today a task can only finish its pull request in two ways:
- **Done at once,** with nobody looking at the PR ("Require human code review" off).
- **Waiting for a person** to merge it (the setting on).

The owner wants a third way: an agent reviews the PR on the host. When it approves, it merges and the task is Done.
When it asks for changes, the task goes back to its agent (piece 3) and comes back for review.

## Goals

1. **One setting replaces the checkbox.** Project › Settings › Workflow shows **"Pull request review"** with three
   options and their help texts.
   - **None:** "The task moves to Done as soon as the agent finishes; nobody reviews the pull request first."
   - **Human:** "The task waits until a person merges the pull request (MegooColab notices when the repository is
     connected, or someone clicks Mark merged)."
   - **Agent:** "An agent reviews the pull request on the host, and merges it when it approves; changes it asks for
     go back to the task's agent (at most 3 rounds, then it asks you)."
   - With **Human** or **Agent**, the work always ends as a pull request, whatever the finishing option says, as the
     checkbox did when on.
   - **Migration:** existing projects get **None** where the checkbox was off and **Human** where it was on.
   - The admin's default for new projects (Admin › Settings) becomes the same three-way choice, migrated the same way.
2. **Choosing the reviewer** (Agent only). A **"Reviewer"** choice offers:
   - **"The task's own agent (fresh session)"**, the default;
   - any agent the project can use.

   A chosen agent must be able to run on the project's repository (bound on its machine). If it can't when the
   review is due, the workflow asks a person (escalation `agent_review_unavailable`).
3. **The agent's review.** After the Finish run opens the pull request, the workflow starts a **review run** of the
   reviewer agent:
   - **Read-only:** it changes no files.
   - **What it judges:** the PR's diff against the approved design and plan, the recorded test runs and decisions,
     and the PR's checks.
   - **Posting:** it posts its review on the host **from the owner's account**, with its own command-line tool (`gh`,
     `glab`, `tea`), as Finish already opens the PR. It is a comment-type review (hosts refuse "Approve" or "Request
     changes" on your own PR) that states its verdict, with a summary and comments on lines.
   - **Marking:** the review body ends with a hidden marker `<!-- megoo:agent-review -->`.
   - **Reporting:** it reports to MegooColab: verdict (approved or changes_requested), a summary, findings (severity,
     file, line, summary), and, when approved, whether it merged.
4. **Approved: it merges.**
   - It waits for the PR's checks with the host tool (`gh pr checks --watch`, or GitLab's merge when the pipeline
     succeeds), then merges.
   - **(my call)** A normal merge commit, the branch not deleted.
   - MegooColab sees the merge (webhook or poll) and the task is **Done**, as with a person's merge.
   - If it approves but **can't merge** (branch protection wants an approval, conflicts, failing checks), it reports
     why. The workflow asks a person (escalation `agent_merge_failed`, with the agent's reason), who can merge it and
     click Mark merged. Accept means "wait for a person to merge".
5. **Changes requested: back to the task's agent.**
   - The task is sent back exactly as in piece 3: stage Build, a fix run that pushes to the same branch, counting
     toward the same 3 rounds per pull request. The trigger is the agent's review.
   - **(my call)** With Agent review this always applies, whether or not piece 3's checkbox is on, since asking for
     changes is the reviewer's whole job.
   - After the fix is pushed, the reviewer **reviews again**, in a new review run.
   - A fourth "changes requested" asks a person, as in piece 3.
6. **People can still act on the host.** A person's own review, `/fix` or merge behaves as in pieces 2 and 3.
   - A person's merge finishes the task, even mid-review.
   - **(my call)** A person's "changes requested" while the agent is reviewing waits until the review run ends.
     Piece 3 already ignores triggers while a run is going.
7. **On the task's Activity,** the review shows once, credited to the agent with its tag:
   - "laptop-claude **agent** approved PR #42 and merged it";
   - "… approved PR #42 (not merged: <reason>)";
   - "… requested changes on PR #42 · 3 findings", with the summary as a quote.

   **(my call)** It comes from the agent's report. Copies of the review and its comments that arrive by webhook
   carrying the marker are not shown again, and never trigger piece 3.
8. **The workflow panel** shows "laptop-claude is reviewing PR #42" during a review run. Afterwards it shows what
   came of the review, as the other stages do.

## Non-goals

- **A separate bot account** for the reviewer. The owner chose their own account.
- **MegooColab posting or merging through the connection's token.** The agent uses its own CLI, as Finish does.
- **Agent review** for the merge-locally or keep-branch finishing options. Agent review forces a pull request, as
  Human does.
- **Choosing the merge method or deleting the branch** after a merge.
- **Reviewing back-merge pull requests** (production fixes). A back-merge PR still waits for a person.

## Anti-goals

- **An endless loop:** review, changes, fix, review again past 3 rounds.
- **A task marked Done** without the pull request actually merged.
- **Two lines in Activity** for one agent review (its report and the webhook copy).
- **A reviewer that edits code** or pushes. It is read-only; only the fix run changes code.

## Constraints

- **Run roles and texts:** the review run is a new run role with its own editable methodology text (Admin ›
  Methodology), read-only, in a fresh session.
- **Frozen settings:** the setting is frozen when the Done stage begins, as the checkbox's value is today
  (`finish_requires_human_review`), so changing it mid-task doesn't change a running task.
- **Locks and dispatch:** everything runs under the engine's existing locks and dispatch. The reviewer may be a
  different agent from the task's assignee.

## Testing

- **Backend:**
  - the migration, None → Done at once, Human → waits, Agent → a review run of the right agent;
  - approved and merged → Done once the merge is seen;
  - approved without a merge → the escalation with its reason;
  - changes requested → sent back, then reviewed again after the fix, and the fourth time escalates;
  - an unavailable reviewer escalates;
  - the marker'd webhook copy is neither shown nor a trigger;
  - a person's merge during a review finishes the task;
  - the setting is frozen at Done.
- **Frontend:**
  - the setting and its help texts, the reviewer choice, and the admin default;
  - the panel line during review;
  - the Activity lines;
  - the escalation texts.
- **e2e:** the git test runs with Agent review:
  - the fake agent's review run reports changes requested, so the task is sent back;
  - the fix run;
  - a second review run reports approved and merged, and the fake host shows the PR merged;
  - the task is Done.

## Left to the builder

- **Names:**
  - the run role and methodology key (`pr_review` suggested);
  - the MCP tool (`submit_pr_review` suggested);
  - the escalation reasons (as above).
- **How the enqueue runs another agent** than the task's assignee.
- **How "merged" is confirmed:** the agent's report alone, or a refresh of the PR right after the run.
  Recommended: queue the PR refresh when the run ends.
