# Knowledge base: write a document with an agent

Status: awaiting the owner's approval. Agreed in conversation:
- the owner chose **Layout A** (draft and conversation side by side);
- the agents are the **same machine agents** as in chats;
- for agent choice per space, the owner answered "yes" to the proposal;
- admins and project managers may pick others' agents, "same like chat";
- the person **types in the draft too**;
- on anti-goals: "we can fix any issues come up later".

Calls I made are marked **(my call)**. The mockup is
`.superpowers/brainstorm/768-1793778942/content/kb-agent-writing.html` (git-ignored).

## Why

Today a person writes a knowledge base document by hand in the Markdown editor. The owner wants people to have one
of their agents write it for them. Then they go back and forth with it ("add a rollback section", "shorten the
intro", "drop the FAQ") and fix things themselves, until they are satisfied and save.

## Goals

1. **Starting.** **Write with an agent** is offered in two places:
   - **KB › New document**, beside the blank document;
   - on an existing document the person may edit, beside **Edit**.

   A dialog asks for:
   - **Agent:** see goal 2.
   - **What the document should be:** a free-text brief. When improving an existing document, this is the first
     request.
   - **Let it read (optional):** tasks (`PAY-12`) and knowledge base documents the agent should read first, using
     the person's own access.
     - **(my call)** The server reads them with the person's access when the draft starts. It hands their text to
       the agent through the draft-reading tool (goal 11).
     - The agent's own MCP tools keep their usual access: a run token acts as the agent's owner, and only for its
       own work.
   - **Save into:** space and folder. New documents only; it defaults to where the person started.

   **Start drafting** opens the writing page (goal 3) and sends the agent its first turn.
2. **Which agents.** The agents are the same machine agents as in chats.
   - **A project's space:** the agents the person may start a chat with on that project, chosen the same way
     (`can_use_agent`, a usable binding).
     - **Others' agents:** as in chats, admins and project managers may pick an agent someone else owns. The owner
       confirmed this. The draft, and what it was pointed to, then go to that agent's machine. In the app the
       draft stays the person's own (goal 7).
     - **The code:** the agent works in the project's repository on its machine, and may read the code to write the
       document. It changes no files there (read-only, as a review run).
   - **A team or the organisation's space:** only the person's own agents, wherever they are bound. The agent works
     in an empty folder of its own on its machine, not in any repository. It reads only what the brief points to,
     plus the knowledge base through its MCP tools.
     - **(my call)** The runner keeps that folder for the whole draft, so the agent's session resumes across
       turns.
     - It is removed when the draft is saved or discarded. That is a new "remove this draft's folder" message from
       the server to the runner.
     - The runner also removes such folders untouched for 30 days, in case it was offline when the message was
       due.
   - The dialog offers only usable agents, online ones first, with the offline ones marked. With none, it says why
     ("No agent can work on this project" / "You have no agents").
3. **The writing page (Layout A).** It is a page of its own, linked from the document and from the person's drafts
   (goal 7).
   - **Left: the draft,** rendered as the document will look.
   - **Right: the conversation** with the agent, in the chat style: the person's requests, the agent's replies,
     "<agent> is writing…" while it works, and **Stop**.
   - **Top bar:**
     - the document's place and title. **(my call)** The person can edit the title there at any time.
       - For a new document, the agent proposes a title with its first turn when the title is still empty.
       - After that, the agent changes the title only when asked, and says so in its reply.
       - A title change is not a mark;
     - "Draft · not saved";
     - the number of changes from the last request, with **Keep all** and **Undo all**;
     - **Save to KB…** and **Discard draft**.
4. **What the agent's changes look like.** Each agent turn changes the draft. One request may change several
   places.
   - **Marking:** every change from the last turn is marked, block by block (a heading, paragraph, list, table or
     code block):
     - **added** (green), **changed** (amber, old words struck, new words shown) or **removed** (pink, struck);
     - each change shows the request it came from;
     - each has **Keep** and **Undo**.
   - **The next request settles them (my call):** sending a new request keeps whatever was not undone, and the marks
     clear, so marks always show the last turn only.
   - **Undo** puts back what was there before the change, as the person last saw it.
   - **The agent's reply** in the conversation says what it did in a sentence or two, and may ask the person a
     question ("I used 1%, is that right?"). It never repeats the whole document.
5. **Aiming a request.** Selecting text in the draft sets the request's target. A chip above the box says "About:
   selected text in '<section>'", next to "whole document", and the request is sent with the target. Without a
   selection, the request is about the whole document.
6. **Typing in the draft.** The person may edit the draft themselves between requests.
   - **Editing:** a toggle switches the left side between the rendered draft and the existing Markdown editor with
     its preview. **(my call)** This reuses `DocEditor`'s editor rather than building a rich-text editor.
   - **The agent sees the edits:** its next turn works on the draft as the person left it, and it must keep their
     edits.
   - **Marks:** the person's own edits are never marked; only the agent's are.
   - **(my call)** Switching to the editor settles the open marks first, keeping every change not undone, so an
     Undo can never bring old text back over the person's edit. The toggle says so when marks are open: "Keeps the
     N open changes".
   - **(my call)** While the agent is writing, the draft is read-only. A banner says so, with **Stop**.
7. **Drafts are kept.** Closing the tab keeps the draft and the conversation, and the person can come back.
   - **(my call)** One draft per person per document. **Write with an agent** on a document that already has the
     person's draft opens that draft.
   - **(my call)** A draft is the person's own: no one else sees it, and the saved document is unchanged meanwhile.
     Others may edit and save the document as usual.
   - **(my call)** **KB** shows a **My drafts** list: title, space, agent, last activity. An existing document the
     person has a draft of shows "You have an unsaved draft with <agent> · Open".
   - **(my call)** Drafts never expire. They end when saved or discarded.
8. **Saving.** **Save to KB…** asks for an optional summary, then saves the draft as a document revision.
   - **A new document** is created in the chosen space and folder.
   - **An existing one** gets a new revision.
   - **Credit:** the revision has the person as `author_user_id` and the agent as `author_agent_id`. The revision
     history shows "<person> with <agent>". The summary defaults to "Written with <agent>".
   - **Unreviewed marks:** saving keeps the draft as shown. **(my call)** If marks are still unreviewed, the dialog
     says "N changes not reviewed" and saves them as kept.
   - **A newer revision:** if the document got a newer revision since the draft started, saving is refused, as in
     `DocEditor`, and the draft is kept. **(my call)** The person then chooses:
     - **Show what changed** (the existing diff of that revision);
     - **Ask the agent to bring it in**, which sends a request with the newer text;
     - **Save over it anyway**, after a confirmation.
   - **After saving,** the draft and its conversation are deleted, the running session ends, and the person lands
     on the saved document.
9. **Discarding** asks for confirmation, then deletes the draft and its conversation. A turn in progress is
   stopped.
10. **The agent's turns are runs.**
    - Each request is an agent run with a new run role (`kb_write` suggested), with its own editable methodology
      text in Admin › Methodology.
    - The runs go through the existing queue, dispatch and concurrency limit (5 runs per agent). They also count
      toward that limit.
    - **(my call)** The agent keeps one session across the draft's turns, as chats do. It starts a fresh one if the
      session is lost, given the brief, the draft and the conversation so far.
    - An **offline** agent's turn waits, with "Waiting for <agent> to come online" in the conversation, as in chats.
    - **Stop** cancels the run. The draft keeps what the agent had applied by then: changes apply in one step at the
      end of the turn, so a stopped turn changes nothing.
11. **How the agent changes the draft.** It uses MCP tools of its own, allowed only in this run role:
    - one to read the draft, the person's target and the brief;
    - one to submit its changes and its reply.

    The server applies the changes, works out the marks, and stores the turn. **(my call)** The agent submits the
    whole new draft. The server diffs it against the draft it was given, block by block, to make the marks. The
    agent never sends a patch format it could get wrong. The size limit is the knowledge base's (500,000
    characters).
12. **Notifications (my call).** When a turn finishes and the person isn't on the page, they get the usual
    notification ("<agent> updated your draft '<title>'"), linking to the writing page. This is the same
    notification as a chat reply.
13. **Phones (down to 280 px).** The writing page has two tabs, **Draft** and **Conversation**. The request box
    stays at the bottom of both. Keep and Undo stay tappable. The page never scrolls sideways.

## Non-goals

- Several people writing one draft together, or seeing each other's drafts.
- Images in the conversation.
- The built-in AI model (Admin › AI) as the writer; only machine agents.
- The agent changing code or files, or saving to the knowledge base itself; only the person saves.
- Agents choosing to write knowledge base documents during task work. That keeps going through `kb_write` as today.

## Anti-goals

- A save the person didn't make: nothing reaches the knowledge base without **Save to KB**.
- Losing the person's own edits to an agent turn.
- Overwriting someone else's newer revision silently.

## Constraints

- **Stack:** the existing pieces: FastAPI and async SQLAlchemy with Alembic migrations, Next.js with TanStack Query,
  the Go runner.
- **Runner:** an empty working folder for agents without a repository is a runner change, so the runner gets a new
  minor version at release. An older runner gets no team or organisation drafting. The dialog says the runner needs
  updating, as the image button does.
- **Run targets:** a run today targets a task or a question (`agent_runs_target_check`). A draft is a third target.
- **Access:** only people who may write in the target space can start, and saving rechecks write access.

## Testing

- **Backend:**
  - agent choice per space kind;
  - a turn: the run is queued and dispatched, and the submission applies with the right marks;
  - keep and undo;
  - the person's edits survive the next turn;
  - a stop changes nothing;
  - saving a new document and an existing one, with the credit;
  - the newer-revision refusal and save-anyway;
  - discard;
  - one draft per person per document;
  - drafts are private;
  - MCP tools refuse other roles.
- **Runner:** a run without a repository gets an empty folder that is removed afterwards.
- **Frontend:**
  - the dialog;
  - the writing page: marks with Keep and Undo, Keep all and Undo all, the target chip, the editing toggle, the
    read-only state while writing;
  - My drafts;
  - the save dialog with unreviewed marks and with a conflict;
  - the phone tabs.
- **e2e:** with the fake agent:
  - start a draft on a project document;
  - the agent's turn adds a section and removes one;
  - undo one change;
  - type an edit;
  - a second turn keeps the edit;
  - save, and the revision shows "<person> with <agent>".

## Left to the builder

- **Names:** of tables, the run role, MCP tools and routes.
- **Diffing:** the block-diff algorithm and how marks are stored.
- **Live updates:** how the page learns of a finished turn. Use the existing realtime channel if there is one for
  chats.
- **The methodology text** for the new role.
