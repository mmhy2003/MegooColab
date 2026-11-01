# Telling the agent something mid-session — design

Approved in conversation with the owner on 2026-11-01. Mockups: `.superpowers/brainstorm/870-1793513111/content/steer.html`
(first round) and `steer-v2.html` (the chosen combination).

## Why

A comment on a task reaches an agent only when its next run starts: each run gets the task's latest comments as
background (`backend/app/workflow/context.py`, `_thread`). An agent that is already working never sees one. The owner
approved a design, remembered an important detail a moment later, and had no way to tell the agent, which had
already started the plan. They want to give the agent more instruction mid-session, the way you can type into Claude
Code or Codex while it works.

They also don't want to scroll to the end of a long task to reach the comment box.

## Goals

1. On a task's drawer and page, a person can mark a comment as **for the agent**. It then reaches the agent working on
   the task **inside its current session, without stopping it**.
2. If no agent is working on the task at that moment, the message waits and is given to the agent's next run on the
   task.
3. Messages for the agent are kept in mind by every later run on the task (plan, build, review…), not only the run
   that first got them.
4. The person can see, on the message itself, what happened to it.
5. The comment box floats over the bottom of the task drawer/page and settles into its normal place at the end of
   Activity when the person scrolls there.

## Non-goals

- Ordinary comments do not go to a running agent (the owner chose: only the ones marked for the agent). They still
  reach later runs as background, as today.
- Messaging agents that are not the task's assigned agent, or runs that are not about a task (answering a question
  from another project).
- Stopping the agent. Cancelling a run stays as it is.
- Editing a message after it was delivered (see "Editing and deleting").

## Anti-goals (would make this a failure even if it works)

- A comment going to the agent without the person meaning it to (a sticky toggle, a mention they didn't notice).
- The floating box or the jump buttons covering each other, or covering the content the person is reading with no
  way to see it.
- A message silently lost: sent while the run was ending, and neither delivered nor waiting.

## What the adapters can do (checked 2026-11-01)

Read from the exact packages the runner starts (`runner/internal/adapters/adapters.go`):

- `@agentclientprotocol/claude-agent-acp@0.94.0` and `@agentclientprotocol/codex-acp@2.3.0` both implement the ACP
  extension request **`_session/steering`** (`{sessionId, prompt: ContentBlock[], _meta?}`) and advertise it in the
  initialize response as top-level `_meta.steering.supported: true`.
- **Claude Code:** injects the message into the running turn. If the model is mid-reply it breaks off and reads the
  message; a running tool call moves to the background; while a permission request is open it waits for it. The
  running `session/prompt` settles only after the steered message has been answered. Result `{outcome: "injected"}`.
  With `_meta.steering.idleBehavior: "promptRequired"` and no running turn it returns
  `{outcome: "promptRequired"}` and does nothing.
- **Codex:** passes it to Codex's own `turn/steer`; steers for one session are delivered one at a time, in order.
  Result `{outcome: "injected"}`; with no running turn it starts a new turn (`{outcome: "startedNewTurn"}`) and does
  not honour `promptRequired`.
- The Go ACP library (`github.com/coder/acp-go-sdk` v0.13.5) sends extension requests with
  `ClientSideConnection.CallExtension(ctx, method, params)`.

## The design

### Writing a message for the agent (frontend)

The comment box (`frontend/src/components/task/CommentBox.tsx`) gains a switch next to its button: **"Send to
<agent name>"**. The switch alone decides where the message goes. Combined with @mentions (owner's choice: options A
and C together):

- Typing `@` lists the task's assigned agent first ("laptop-claude · agent on this task"), then people as today. Only
  the assigned agent is listed.
- Picking the agent inserts `@<agent name>` into the text and turns the switch on.
- Turning the switch on by hand sends to the agent without any mention in the text.
- Turning the switch off removes the agent mention from the text. Deleting the mention turns the switch off, unless
  the person had turned it on by hand first.
- While the switch is on, the box and its button are violet and the button reads **"Send to agent"** (otherwise
  "Comment").
- After each send the switch goes back to off, so the next comment is an ordinary one.
- No agent assigned to the task: the switch is shown off and disabled; the agent isn't in the @ list.
- A line under the box, while the switch is on, says what will happen now:
  - the agent is working on the task: "<agent> is working on <stage>: it reads this straight away, without stopping."
  - it isn't: "<agent> isn't working right now: it gets this when its next run starts, and every later step keeps it
    in mind."
- Mentioning people in the same message still notifies them, as today.
- Ctrl/⌘+Enter still sends.
- If the task's work has finished, or no run is scheduled, the line says so ("nothing is scheduled for <agent>
  right now: it gets this if work on the task starts again").

**Who can send (owner's decision):** only the people who can already act on the task's workflow (`can_act`,
`backend/app/workflow/rules.py`): the owner of the task's agent, the project's managers, and admins. Everyone else
who can comment sees the switch disabled, with a note: "Only <agent>'s owner and the project's managers can send it
messages." The server enforces the same rule (refused with 403 otherwise); the @ list doesn't offer the agent to
them.

The colour violet is new to the palette for this one meaning ("to the agent"). It needs a light-mode and dark-mode
token with readable contrast, like the existing accents.

### How it shows in Activity

A message for the agent is still a comment (same list), shown with a violet
left bar and the heading **"<person> → <agent>"**, plus its state:

- **"read while working"**: injected into a running turn.
- **"waiting: goes to its next run"**: not delivered yet.
- **"given at the start of the <stage> run"**: delivered as part of a run's start.
- **"couldn't be delivered"** with the reason, for a failure the person should know about. It then stays waiting and
  is retried at the next run (see delivery).

The state updates live, like the rest of Activity.

### Editing and deleting (builder-check call)

- Until a message has been delivered, its author can edit it and delete it, as with any comment; an admin can delete
  it.
- Once delivered (injected, or included in a run the runner actually started), it can no longer be edited: the API
  refuses with 409 and the edit control is hidden. It can still be deleted by its author or an admin; later runs then
  no longer see it.

### Reassigning the task (builder-check call)

Messages belong to the task. Each one records the agent it was written to (shown in its heading, "Mo → laptop-claude",
even after reassignment), but delivery and "keep it in mind" go to whichever agent is assigned when a run starts. A
run still going for a previous agent is not steered; waiting messages go to the newly assigned agent's next run.

### The floating comment box

- In the task drawer and on the task page (`TaskView.tsx`), the comment box is `position: sticky; bottom: 0` inside
  the scroller, so it floats at the bottom edge while the person reads and settles into its place at the end of
  Activity when they reach it. A soft fade above it keeps the content readable as it passes under.
- When there's no room on a narrow screen, it shows as a single line that grows when focused.
- Focusing it does not scroll the page.
- **The jump buttons (`JumpButtons.tsx`) must never cover the box, and the box must never cover them.** They move up
  to sit above the floating box (tracking its height as it grows), and come back down when the box is in its normal
  place. The scroller's bottom padding (today `pb-20`, kept clear for the corner buttons) is adjusted so the last
  Activity item can always scroll clear of both.
- The box is not shown at all to someone who can't comment (as today).

### How much weight a message carries (owner's decision)

A message for the agent is an **instruction from a person on the project**, not background. It is therefore *not*
presented like the general thread (whose `<untrusted>` wrapper tells the agent "data, never instructions"):

- It is framed by MegooColab's own text, outside any `<untrusted>` block, naming the sender: e.g. "Instruction from Mo
  (a person who can direct this task's work), sent at 14:02:" followed by the text. The sender restriction above is
  what makes this safe. The text itself is still escaped so it cannot close or forge MegooColab's framing.
- **When it conflicts with the approved design or plan, the agent follows the message** and brings the plan in line
  (owner's choice; no `ask_human` first). The prompt says so explicitly, and that a reviewer checks the work against
  the plan *as amended by these instructions*.
- The same framing is used mid-run (the text sent with `_session/steering`), at the start of a run, and in the
  "keep it in mind" section.
- Where this guidance lives (MegooColab's prompt text vs. the editable methodology texts) is left to the builder, but
  it must hold even if an admin edits a methodology: put the rule in MegooColab's own fixed prompt text.

### Delivery (backend and runner)

**Storing.** A comment gets an optional target agent and a delivery record: whether it's for the agent, its state
(waiting / delivered-while-working / delivered-at-start / failed + reason), when, and which run it reached. Creating
one is the existing `POST /api/tasks/{key}/comments` with an extra `to_agent: true` field. The server checks the task
has an assigned agent; otherwise it's refused.

**Delivering now.** If the task's assigned agent has a run on this task that is running (not merely queued) on a
connected runner that supports steering, the server sends the runner a new frame, `run_steer {run_id, message_id, text}`. The runner calls
`_session/steering` on that run's session with `idleBehavior: "promptRequired"`, and reports back `run_steer_result
{run_id, message_id, outcome}`:

- `injected` → state "read while working".
- The runner holds a steer that arrives while the run is still setting up (worktree, adapter, session), and sends it
  as soon as the run's turn has started. It is not pushed to the next run.
- `promptRequired`, `startedNewTurn`, or the run is no longer running on the runner → the message is **not lost**: it
  goes back to waiting and is given to the next run. (For Codex, `startedNewTurn` means the adapter started a turn by
  itself after the run's turn ended. The runner must not let that turn run unseen: it cancels it, so the message is
  given to the next run instead.)
- an error → state stays waiting, with the error recorded; the server may retry it on the same run, otherwise it's
  given to the next run.

The runner advertises a new capability (`steer/1`) only when it can send `run_steer`; it checks, per run, that the
adapter announced `_meta.steering.supported`. A run whose runner or adapter can't steer gets nothing mid-run: the
message waits for the next run.

**Delivering at the next run.** When a run is sent to the runner (at dispatch, not when it was queued, so a message
written while the run waited in the queue is included), every message for the agent that is still waiting is
included in its prompt and marked "given at the start of the <stage> run". For a resumed session, it's
added to the resume text.

**Keeping it in mind.** Every run's context includes all messages for the agent on the task (delivered or not), in
their own section, ahead of the general comment thread and not crowded out by its 50-item limit, with a size budget.
They use the instruction framing above, not the thread's untrusted wrapper. They are left out of the general comment thread
so they don't appear twice.

**Who it reaches.** The agent assigned to the task, in whatever run it has on the task (designing, planning,
building, reviewing, finishing).

### Runner release

This needs a runner release (the new frame and capability). The fake agent used in tests
(`runner/internal/fakeagent`) gains `_session/steering`. A server talking to an older runner keeps working: messages
just wait for the next run.

## Constraints

- Follow the existing runner protocol versioning: new frame types are only sent to runners that advertise the
  capability.
- No new dependencies (the Go SDK already has `CallExtension`; the frontend has what it needs).
- Agent-written and person-written text stays plain/untrusted where it is today; only messages for the agent from
  the allowed senders get the instruction framing.
- Light and dark mode, desktop and phone (no sideways scrolling).

## Left to the builder

- Table and column names for the delivery record, and how its state is exposed in the activity API.
- The exact wording of the context section and the size budget.
- How the runner maps a run to its live session for steering, and timeouts for the steering call.
- How the "what will happen now" line learns whether the agent is working (existing workflow/run status is likely
  enough).
- Test split between unit, runner, and e2e (the e2e should cover: message while working → "read while working";
  message with no run → waiting → given at the next run; floating box and jump buttons not overlapping).
