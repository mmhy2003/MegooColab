# A model and effort for each workflow stage — design

Status: approved by the owner on 2026-11-13. The owner chose the placement (on the agent) from a mockup and approved this document, including the table in mockup A.
Calls marked *(my call)* were made while writing this up.

## Why

The owner wants different models for different kinds of work: a deep-thinking model such as Fable for design and
planning, then Opus for building. Today an agent has one model and one effort (Agents → the agent → Settings), and
every run of that agent uses them. Changing them by hand between stages is slow and easy to forget.

## Goals

- On an agent's settings, a **Model by stage** table sets the model and effort for each stage of the workflow. A
  stage left as "As above" uses the agent's own Model and Effort, as today.
- Each workflow run starts on its stage's model and effort, including a run that continues an earlier session (the
  plan run after the design run, a step's fix after its review).
- The choices offered are the ones the agent's own program offers, so a Claude Code agent and a Codex agent each
  list their own models.

## Non-goals

- No per-project or per-task settings. The owner chose the agent, because a project's tasks can go to agents of
  different programs (Claude Code, Codex, OMP) that offer different models.
- No different model for chats, scheduled jobs, answers to other projects or Knowledge Base drafts: they keep the
  agent's own Model and Effort. *(my call)*
- No change to how a stage's work is split between agents.

## Anti-goals

- A run silently using a model other than the one its stage asks for. If a run can't get its stage's model and
  effort, it fails the way a run fails today when the agent's own model is unavailable (`model_unavailable`,
  `effort_unavailable`), and says so.
- A stage running on the model of the stage before it because the session was continued. A continued session must
  be put back on the agent's own model when its stage says "As above".

## Decided with the owner

- **Placement: on the agent**, under its Model and Effort, as in mockup A
  (`.superpowers/brainstorm/1055-1794578782/content/stage-models.html`).
- **The table:** one row per stage with a Model and an Effort picker. Each defaults to "As above (<the agent's
  model / effort>)". Rows that differ from the agent's own settings are marked, as the mockup's violet borders show.
  The table's look is mockup A; approving this document approves it.

## The stages *(my call)*

Grouped by the kind of work, so a writer stage and a reviewer stage can differ:

| Row | Run roles |
|---|---|
| Design | `brainstorm` |
| Plan | `plan` |
| Build — steps and their fixes | `implement`, `step_fix`, `final_fix`, `pr_fix` |
| Review — step and final reviews | `step_review`, `final_review`, `pr_review` |
| Finish | `finish` |

`freestyle`, `cron`, answering and draft runs use the agent's own Model and Effort.

## How it behaves

- **Picking:** the Model list is the agent's `known_models` (what its program offered on its last run), plus typing
  a name, exactly as the existing Model field (`frontend/src/components/agents/ModelField.tsx`) works. The Effort
  list is the levels the chosen model offers. Picking a model that doesn't have the row's effort resets that row's
  effort to "As above" with the same kind of note the existing field shows.
- **Saving:** each change saves at once, like the agent's other settings. A run that's already going keeps the model
  it started on; the next run uses the new choice.
- **Which model a run gets:** the run's role maps to a row. *(my call, after the builder check)*
  - The row sets a model: the run uses that model, and the row's effort if it sets one, otherwise **that model's own
    default effort** (not the agent's: Fable may not offer the effort the agent's model uses). In the table, such a
    row's Effort picker reads "Model default", not "As above".
  - The row sets only an effort: the run uses the agent's model with the row's effort.
  - The row sets neither: the agent's own model and effort, as today.
- **Keeping rows valid:** when the agent's own model changes and a row that sets only an effort names a level the
  new model doesn't offer, that row's effort goes back to "As above" with a note, as the agent's own Effort does
  today. *(my call)*
- **Continued sessions:** the runner already sets the model and effort on every session it opens, including one it
  resumes (`runner/internal/jobs/manager.go`, `startModel` after `openSession`). Because a continued session may
  have been switched to another stage's model, a run whose row says "As above" must still put the session on the
  agent's own model and effort. Today an empty model or effort means "change nothing", which would leave the
  session on the previous stage's model.
  - *(my call, after the builder check)* The runner learns each program's **starting model and effort**: the values a
    fresh session reports before the runner changes anything. Not every program lists a "default" value (Codex takes
    any name), so this is the only definition that works for all of them. The runner keeps them per program and
    keeps them across restarts (a small file in its own config folder), as it already learns each program's effort
    levels on the first run.
  - When a run asks for no model or no effort of its own and its session is resumed, the runner switches the
    session back to the program's starting value if the session reports anything else. If the runner doesn't know
    the starting value yet, it opens a fresh session for the run instead of resuming, since a wrong model is worse
    than a lost conversation. The run's prompt for a fresh session is already built for that case.
  - Whether a program keeps a resumed session's last model at all is for the builder to check per program (Claude
    Code, Codex, OMP); where it doesn't, no switch is needed, and the tests say so.
- **Seeing it:** Activity already records each run's model and effort ("used the model Fable 5.2 with High
  effort"). Nothing new is needed there.

## The runner

Today the runner takes the model and effort from the agent (sent in `welcome` and agent updates), not from the run.
A run-level choice needs:

- `run_start` gains optional `model` and `effort` fields. When present, they replace the agent's for that run.
- A new runner capability *(my call: `stagemodel/1`)* says the runner understands them. The Go runner ignores
  unknown fields, so without the capability the server must not rely on them.
- **An older runner** *(my call)*: a run whose stage sets a model or effort waits for a runner with the capability,
  as runs already wait for `model/1` when the agent has a model of its own. The agent shows the existing kind of
  "update the runner" problem while that's the case. Runs whose stage says "As above" are unaffected.
- This needs a runner release. The server still talks to older runners as before.

## Data

- The agent gets a `stage_models` setting: for each row, an optional model and an optional effort. Empty means "As
  above". Shape and storage are the builder's (a JSONB column keyed by row name fits the agent's existing
  `known_models`). Needs a migration, made and tried on `megoo_migrate` as AGENTS.md says.
- Only the agent's owner (and whoever may edit the agent's settings today) may change it, through the same agent
  update API, which records the change as it does for model and effort.

## Left to the builder

- The exact API shape and validation (lengths as for the existing model and effort names).
- How the table looks on a phone (the agent page already stacks its fields there).
- Tests: the role-to-row mapping, a run on each row getting its model and effort, a continued session going back
  to the agent's own model, the waiting rule for older runners, and the UI's lists and resets.
