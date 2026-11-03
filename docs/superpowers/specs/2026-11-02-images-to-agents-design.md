# Images to agents, in chats and tasks

Status: draft for the owner's review; the owner settled the fallback folder and connect-only delivery after the
builder check. Builds on develop as of a242b67 (MegooColab 0.9.1, runner 0.5.0).
Mockups the owner approved: `.superpowers/brainstorm/7234-1793645187/content/chat-images.html` (chat) and
`task-images.html` (task).

## Why

The owner wants to send images (screenshots, designs, photos of a bug) to an agent alongside a message, so the
agent works on them: "the checkout button is cut off, see these". Today a chat message and a task comment are text
only, and a task's Attachments are files for people that no agent ever sees.

## Goals

- In a **chat**, every message box takes images: the chat's message box and **New chat**'s first message. The
  images go with that message whatever it does (tells the agent, answers its question, asks for changes to a design
  or plan, starts a new round).
- In a **task** (its page and its drawer), the comment box takes images, with **Send to agent** on or off, and so
  does the answer box of the agent's questions on the task.
- The agent **sees the images**, the way pasting a screenshot into Claude Code works, for every agent program
  (Claude Code, Codex, OMP).
- The images show in the conversation, with the message they came with, and in the task's **Attachments**.

## Non-goals

- The agent putting the images into the project as files (a logo to add to the site). It only looks at them. (The
  owner was asked and did not ask for this; it can come later.)
- Images in Telegram, email or push notifications; files other than images in a message (PDFs stay a task
  Attachments upload, for people).
- Editing a sent message's images, or images in a design or plan document.
- Agents sending images back.

## Anti-goals

- An image that looks sent but that the agent never sees. If the agent's runner can't deliver images, the person
  can't send them (the button is off and says why); if the program can't take them in its prompt, the fallback
  still gets them to it.
- Images ending up in the project's files or its git history.
- A message box that gets slower or harder to use for text-only messages.
- A way to put arbitrary files or scripts on the server behind an image's name (only real images are accepted,
  and they are served so a browser never runs them).

## What the person sees

### The message box (chat and task, the same component)

- An **Add images** button beside the box's other controls. Images also come in by **pasting** (Ctrl/Cmd+V a
  screenshot) and by **dropping** files on the box, which shows a dashed "Drop images to add them" area while
  dragging.
- Each image uploads **as soon as it is added**, showing a thumbnail with a progress bar, then the thumbnail with
  a ✕ to take it out. **Send** waits while an upload is in flight. Text stays required, as today (my call: an
  image without words leaves the agent guessing what to do with it).
- Limits, checked on the server and said under the box in one line when something is refused:
  "<name>: only images can be sent (PNG, JPEG, GIF or WebP, up to 5 MB each, 6 per message)." A counter "3 of 6"
  shows once there is at least one.
- When the images can't reach the agent, **Add images** is greyed out with a hint saying why:
  - the agent's runner is older than 0.6.0 (it lacks the `images/1` capability): "Update the runner on
    <agent>'s machine to send images.". The server remembers each runner's capabilities from its last hello, so
    an agent whose machine is **offline** but last connected with `images/1` can be sent images (they wait for the
    next run, like the message); one that has never connected is greyed out with the same hint;
  - in a task, with **Send to agent** off, images are allowed (they are for people) whatever the runner.
- In a task with **Send to agent** off, the hint under the box says the agent sees that the comment had images,
  not the images.

### In the conversation

- A message with images shows them under its text as thumbnails, up to three across (chat bubbles, task Activity
  comments, a question's answer, a change request).
- Clicking one opens a full-size view over the page: ← → (and arrow keys) through that message's images, the file
  name and size, **Download**, Esc or a click outside to close.

### The task's Attachments

- Images sent with messages are listed there too, with a small thumbnail and "from <name>'s comment" (or answer,
  or change request) linking to the message in Activity. Files uploaded there directly stay as today (any type, up
  to the current 25 MB), with a thumbnail when they are images.
- Deleting an image from Attachments takes it out of its message too. Deleting a comment keeps its images in
  Attachments (as files of the task).
- A chat's round is a task, so a chat's images are its round's attachments.

## How the images reach the agent

1. **Storage.** Images are task attachments (the existing `attachments` table and upload folder), linked to the
   message they were sent with. Uploads made before Send (and before New chat has created its round) are held as
   the uploader's, not yet linked; Send links them. Unsent uploads are removed after a day.
2. **Which message, which run.** An image is delivered with its message, by the route the message already takes:
   - a message to the agent while it runs is handed into its running session (run_steer) with its images;
   - otherwise it is kept for the next run (as messages are today), whose prompt carries it with its images;
   - an answer and a change request reach the agent in the next run's prompt, as today, with their images.
   A run that **resumes** a session (an answer or change request going back to the session that asked) carries
   only the images that session hasn't had: the new message's. A run in a **fresh** session carries the images of
   the messages its thread and instructions include, newest first, **at most 10 per run**; a message whose images
   didn't fit says so in the prompt ("2 more images on this comment were left out"). Plain comments (not to the
   agent) carry no images, only a note: "(this comment had 2 images, for the people on the task)".
   **Delivered or not.** Each image remembers whether the agent has had it. A run or steer that has images not yet
   delivered goes only to a runner with `images/1` and otherwise waits for one, as an OMP run waits for `omp/1`
   (rare: sending needs a runner that had `images/1`, see below; it happens after a reassignment or a runner
   downgrade). Images already delivered never hold a run up: on a runner without `images/1` they become a line
   naming them.
3. **The prompt text** names each image where its message is ("[image 1: phone-ios.png]"), so the agent can tell
   which picture goes with which words. Image content is untrusted, like the thread's text: the prompt says so.
4. **The runner (0.6.0, capability `images/1`)** gets the list of images for a run start or a steer (id, name,
   type, size), downloads each one from the server with its runner token, and:
   - puts them in the ACP prompt (or the steering call, which also takes content blocks) as image blocks after the
     text, when the agent program says it takes images (`promptCapabilities.image`);
   - otherwise saves them to a temporary folder outside the project, gives their paths in the text ("open these
     with your file reader"), and removes the folder when the run ends. The runner's policy lets the agent
     **read that one per-run folder** (it holds nothing but the run's images), under every policy including
     `workspace`; every other read outside the worktree stays refused as today (the owner's decision).
   A download that fails fails that delivery like any other (the run doesn't start / the steer reports failed), so
   nothing goes out silently without its images.
5. **Connect-only tasks** (no runner: the person's own coding agent works the task through MegooColab's MCP
   tools) get images too, by MCP (the owner's decision). The tools that hand that agent the task's thread, answers
   and change requests (`get_task`, and `get_workflow` where it carries them) return the images of the messages
   they include as MCP image content, with the same per-call cap of 10, newest first, and the same note for
   images left out; an image counts as delivered once a tool has returned it. The MCP token's access to the task
   is the access check. The boxes there take images whatever runner the person has.
6. **Access.** The runner may download only images of runs (and steers) sent to it; a person may see an image only
   if they can see its task. Images are served with their real image type, `nosniff`, and never as HTML or SVG.

## Constraints

- Accepted: PNG, JPEG, GIF, WebP, recognised from the file's contents, not its name or the browser's type. Up to
  5 MB each, 6 per message, 10 per run's prompt.
- Older runners keep working: a server never sends image lists to a runner without `images/1`, and the runner
  0.6.0 keeps working with older servers.
- Reuse what exists: the attachments table and folder, `Attachments`, the comment box (`CommentBox`) and chat
  composer (`ChatComposer`), the activity thread rendering (`ActivityThread`, which the chat also uses), the runner
  capability check used for OMP (`registry` `has_capability`).
- Tests: backend (upload checks, linking on send, access, prompt and run start/steer contents, the 10-image cap,
  cleanup), web (the box: button, paste, drop, refusals, greyed out; thumbnails and the full-size view), runner
  (download, image blocks, the file fallback and its read allowance, cleanup), MCP (a connect-only task's tools
  returning image content) and e2e (a chat message with an image reaching a fake agent
  as an image block; the same from a task comment sent to the agent).
- Release: MegooColab 0.10.0 and runner 0.6.0, with notes. Saying "release" stays the owner's call.

## Calls I made (the owner can overrule)

- Text stays required: no image-only messages.
- The limits: PNG/JPEG/GIF/WebP, 5 MB each, 6 per message, 10 per run's prompt.
- Plain task comments' images stay with people; the agent gets a note that they exist.
- The runner's fallback folder is a temporary one outside the project, removed when the run ends.
- Unsent uploads are removed after a day.
- Deleting a comment keeps its images in Attachments.
- An offline agent can be sent images when its runner last connected with `images/1` (the server keeps each
  runner's last known capabilities).
- Undelivered images make a run wait for a runner with `images/1`; delivered ones never hold a run up.
- A resumed session gets only the new message's images; a fresh session gets the newest 10.

## Left to the builder

- The data model for linking an attachment to its message (a column per kind of message, or one reference), and
  for unsent uploads.
- The protocol fields for the image list, and the runner's download endpoint and its auth check.
- The full-size view's component and styling, thumbnail sizes, and how images are resized for display (if at
  all).
- How the 10-per-run cap picks when a prompt includes more (newest first is the rule; the details are the
  builder's).
