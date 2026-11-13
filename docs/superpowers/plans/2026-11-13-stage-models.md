# Model and Effort by Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An agent's owner sets a model and effort per workflow stage (Design, Plan, Build, Review, Finish); each workflow run starts on its stage's choice, and a continued session is put back on the agent's own model when its stage asks for none.

**Architecture:** The agent gets a `stage_models` JSONB setting. The server maps a run's role to a stage row and, to a runner with the new `stagemodel/1` capability, sends `run_start.model_choice` with the resolved model and effort ("" = the program's starting model / the model's default effort). The runner remembers each program's starting model (persisted) and each model's default effort (learned with its levels), and applies an explicit choice even on a resumed session. The agents page gets a Model by stage table.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), Go + acp-go-sdk (runner), Next.js + Vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-11-13-stage-models-design.md`

## Global Constraints

- Work on branch `feat/stage-models`; commit per task with `type(area): what changed` subjects and the body/attribution AGENTS.md asks for.
- TDD: every behaviour starts with a test you watched fail.
- Rows and roles, exactly: `design` = `brainstorm`; `plan` = `plan`; `build` = `implement`, `step_fix`, `final_fix`, `pr_fix`; `review` = `step_review`, `final_review`, `pr_review`; `finish` = `finish`. `freestyle`, cron, answering and draft runs never get a stage choice.
- Resolution: row sets a model → (row model, row effort or ""); row sets only an effort → (agent model or "", row effort); row sets neither → (agent model or "", agent effort or "").
- `model_choice` is sent only for workflow runs of a role in a row, only when the agent has at least one row set, and only to a runner with `stagemodel/1`. Otherwise run_start is exactly as today.
- An older runner: runs of a role whose row sets a model or effort stay queued; the agent shows `STAGE_MODEL_PROBLEM`. Other runs are unaffected.
- Migrations only against `megoo_migrate` (AGENTS.md), with an explicit down/up check.
- Model names ≤ 100 chars and efforts ≤ 40 chars, blank = unset (the existing `ModelName` / `EffortName` types).
- No Prettier on files not otherwise changed. Frontend tests run from PowerShell (`npx vitest run …`), not Git Bash.

## Review Focus

1. A resumed session that a previous stage put on Fable, whose stage now says "As above" and whose agent uses the program default: it must end on the program's starting model, not Fable (Task 2 test `TestAnExplicitChoiceOnAResumedSessionGoesBackToTheStartingModel`).
2. A runner restarted mid-workflow, so it doesn't know the starting model yet: the run must open a fresh session carrying the resume prompt, not resume on the wrong model (Task 2 test `TestUnknownStartingModelOpensAFreshSessionWithTheResumePrompt`).
3. An agent with stage rows set, served by a runner without `stagemodel/1`: only the overridden roles wait; a freestyle run still goes (Task 4 test `test_an_older_runner_leaves_only_overridden_stages_queued`).
4. Changing the agent's own model so an effort-only row names a level the new model lacks: that row's effort resets with a note (Task 5 test "resets an effort-only row the new model lacks").
5. An agent with no rows set: run_start has no `model_choice` and resumes behave exactly as today (Task 4 test `test_no_rows_no_model_choice`).

---

### Task 1: Runner protocol — `model_choice` and `stagemodel/1`

**Files:**
- Modify: `runner/internal/protocol/protocol.go` (RunStart ~218-255, capability consts ~54-86, hello ~322)
- Test: `runner/internal/protocol/protocol_test.go`

**Interfaces:**
- Produces: `type RunModelChoice struct { Model string `json:"model"`; Effort string `json:"effort"` }`; `RunStart.ModelChoice *RunModelChoice `json:"model_choice,omitempty"``; `const CapabilityStageModel = "stagemodel/1"` advertised in every hello.

- [ ] **Step 1: Write the failing tests** — `TestRunStartDecodesModelChoice` (decoding `{"model_choice":{"model":"","effort":"max"}}` gives a non-nil choice with `Model==""`, `Effort=="max"`; a run_start without the key gives nil) and extend the existing hello test so its capabilities include `"stagemodel/1"`.
- [ ] **Step 2: Run** `cd runner && go test ./internal/protocol/` — Expected: FAIL (undefined `ModelChoice` / missing capability).
- [ ] **Step 3: Implement** the type, field and constant above (comment: only sent to a runner advertising it; "" means the program's starting model / the model's default effort), and add the constant to the hello's capability list.
- [ ] **Step 4: Run** `go test ./internal/protocol/` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(runner): run_start can carry a model and effort for the run (stagemodel/1)`.

### Task 2: Runner — apply a run's model choice, also on a resumed session

**Files:**
- Create: `runner/internal/jobs/starts.go` (persisted starting models)
- Modify: `runner/internal/jobs/model.go` (efforts cache gains default efforts; `choice`; `startModel`), `runner/internal/jobs/session.go` (`openedSession.resumed`, `sessionRequest.fresh`), `runner/internal/jobs/manager.go` (~76, ~85-95 `New`, ~899-912), `runner/internal/fakeagent/main.go` (~135-145 `begin`)
- Test: `runner/internal/jobs/model_test.go`

**Interfaces:**
- Consumes: Task 1's `RunStart.ModelChoice`.
- Produces (package-internal): `type starts struct` with `loadStarts(path string) *starts`, `(s *starts) get(program string) (string, bool)`, `(s *starts) set(program, model string)` (writes `<cacheRoot>/model-starts.json`, a `{program: model value}` object; a write error is logged, not fatal). `choice` gains `explicit bool` and `starts *starts`. `efforts` also keeps `defaults map[program]map[model]string`: the effort a model reports right after the session is switched to it (learned in `levels`, alongside its levels).
- Fake agent: `FAKEAGENT_RESUME_MODEL` / `FAKEAGENT_RESUME_EFFORT`: a resumed or loaded session starts on these (a program that keeps a session's model) instead of `default`.

- [ ] **Step 1: Write the failing tests** in `model_test.go` (use `fakeModels`/`fakeEfforts`, `newEnvWithCache`, a `startRun` variant that sets `ModelChoice` and `ResumeSessionID`; `FAKEAGENT_RESUME=1`):
  - `TestAModelChoiceReplacesTheAgentsForTheRun`: agent welcomed on `opus`/`high`; run with `ModelChoice{Model:"sonnet", Effort:"low"}` → report `PromptModel=="sonnet"`, `PromptEffort=="low"`; the `model` update says sonnet/low.
  - `TestAModelWithoutAnEffortRunsOnItsDefaultEffort`: session resumed on `opus`/`max` (`FAKEAGENT_RESUME_MODEL=opus`, `FAKEAGENT_RESUME_EFFORT=max`), choice `{Model:"opus", Effort:""}` → `PromptEffort=="default"`.
  - `TestAnExplicitChoiceOnAResumedSessionGoesBackToTheStartingModel`: one fresh run first (records the start `default`), then a resumed run with `FAKEAGENT_RESUME_MODEL=opus` and choice `{"", ""}` → `PromptModel=="default"`.
  - `TestUnknownStartingModelOpensAFreshSessionWithTheResumePrompt`: new cache dir, resumed run with choice `{"", ""}` → the fake recorded a `new` session (not resume/load) and the prompt it got is `Prompt + "\n\n" + ResumePrompt`.
  - `TestTheStartingModelIsKeptAcrossRestarts`: a fresh run, then a new `Manager` on the same cache dir resumes with choice `{"", ""}` and does not fall back to a fresh session.
  - `TestWithoutAModelChoiceAResumedSessionKeepsItsModel`: resumed on `opus`, no `ModelChoice`, agent with no model → `PromptModel=="opus"` (today's behaviour, unchanged).
- [ ] **Step 2: Run** `go test ./internal/jobs/ -run 'ModelChoice|DefaultEffort|StartingModel|KeepsItsModel'` — Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Fake agent: in `begin`, a `resume`/`load` session takes the two env values when set.
  - `starts.go`: as in Interfaces; `Manager.New` loads it from `filepath.Join(cacheRoot, "model-starts.json")`.
  - `session.go`: `openedSession.resumed` is true only when `resumeSession` succeeded. With `sessionRequest.fresh`, skip the resume and build the prompt as the resume-failure path does (Prompt, then ResumePrompt), logging `runner: fresh_session: the starting model of <program> is not known yet`.
  - `manager.go`: `want := choice{model: agent.Model, effort: agent.Effort, ...}`; when `rs.ModelChoice != nil`, use its values with `explicit: true`. Set `fresh` when the choice is explicit, its `Model == ""`, `rs.ResumeSessionID != ""` and `starts.get(program)` has nothing.
  - `startModel`: on a session that isn't `resumed`, record `sel.CurrentValue` as the program's start (before any change). When `explicit`: the target model is the resolved `wantModel`, or the recorded start when `wantModel == ""`. The target effort is the resolved `wantEffort`, or the target model's default effort from `efforts.defaults` when `wantEffort == ""` (unknown default: leave the effort as it is). Switch whenever the session's current value differs from the target. Without `explicit`, today's behaviour is unchanged.
- [ ] **Step 4: Run** `go test ./...` in `runner/` — Expected: PASS (the known-flaky `TestSteerAfterTurnEndsReportsNotRunningAndCancelsStrayTurn` aside: rerun once if it alone fails).
- [ ] **Step 5: Commit** `feat(runner): a run's model choice applies even to a continued session`.

### Task 3: Backend — the agent's `stage_models` setting

**Files:**
- Modify: `backend/app/agents/models.py` (~38-44), `backend/app/agents/schemas.py` (`AgentPatch`, `AgentOut`), `backend/app/agents/router.py` (~83-90), `backend/app/agents/service.py` (~280-298)
- Create: migration via `backend/scripts/makemigration.sh "agent stage models"` (against `megoo_migrate`)
- Test: `backend/tests/agents/test_stage_models.py`

**Interfaces:**
- Produces: `Agent.stage_models: Mapped[dict]` (JSONB, `server_default '{}'::jsonb`), shape `{"design": {"model": "fable", "effort": "max"}, ...}`: only set rows, only set keys. Schemas: `StageRow = Literal["design","plan","build","review","finish"]`; `class StageChoice(BaseModel): model: ModelName | None = None; effort: EffortName | None = None`; `AgentPatch.stage_models: dict[StageRow, StageChoice] | None = None` (when sent: replaces the whole setting; rows with neither are dropped); `AgentOut.stage_models: dict[str, StageChoice] = {}` (shown to everyone who sees the agent, like `model`).

- [ ] **Step 1: Write the failing tests:** `test_stage_models_start_empty` (`POST /api/agents` → `stage_models == {}`); `test_stage_models_are_set_replaced_and_cleared` (PATCH `{"design": {"model": "fable", "effort": "max"}, "plan": {"effort": "high"}, "build": {}}` → GET shows design and plan only; PATCH `{}` clears; an audit row `agent.model_changed` with `data["stage_models"]` is recorded on each change); `test_unknown_stage_or_long_names_are_refused` (`{"deploy": {...}}` → 422; a 101-char model → 422; blank strings become unset); `test_only_the_owner_changes_stage_models` (another user's PATCH → 404 as for `model`).
- [ ] **Step 2: Run** `uv run pytest tests/agents/test_stage_models.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** the column, migration (check `alembic downgrade -1 && alembic upgrade head` on `megoo_migrate` as AGENTS.md shows), schemas, the PATCH handling (stored with `model_dump(exclude_none=True)` per row; recorded in the same `agent.model_changed` audit entry, its data gaining `stage_models`) and `stage_models` in the agent dicts the service returns.
- [ ] **Step 4: Run** `uv run pytest tests/agents -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(agents): an agent keeps a model and effort for each workflow stage`.

### Task 4: Backend — runs get their stage's model

**Files:**
- Create: `backend/app/agents/stage_models.py`
- Modify: `backend/app/runner/protocol.py` (`RunStart`), `backend/app/runner/registry.py` (~22-40), `backend/app/agent_runs/service.py` (`_claim_next` ~225-247, `_send_start` ~388-432), `backend/app/agents/service.py` (`agent_problems` ~98-116 and its caller ~290)
- Test: `backend/tests/agents/test_stage_models.py`, `backend/tests/runner/test_protocol_v2.py` (`test_v2_start_fields_are_exactly_the_non_v1_fields` gains `"model_choice"`)

**Interfaces:**
- Consumes: Task 3's `Agent.stage_models`.
- Produces: `STAGE_ROWS: dict[str, frozenset[RunRole]]` (Global Constraints mapping); `row_for(role: RunRole) -> str | None`; `run_model(agent: Agent, role: RunRole) -> RunModelChoice | None` (None when the agent has no rows or the role has no row; else the Global Constraints resolution); `overriding_roles(agent: Agent) -> set[RunRole]` (roles whose row sets a model or effort). Protocol: `class RunModelChoice(BaseModel): model: str = ""; effort: str = ""`; `RunStart.model_choice: RunModelChoice | None = None`. Registry: `STAGE_MODEL_CAPABILITY = "stagemodel/1"`, `STAGE_MODEL_PROBLEM = "runner too old to choose a model per stage — update megoocolab-runner"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_each_role_maps_to_its_row` (every row's roles; `freestyle` → None).
  - `test_run_model_resolution` (agent `opus`/`high`: design `{fable, max}` → `("fable","max")`; plan `{fable}` → `("fable","")`; build `{effort: low}` → `("opus","low")`; review unset → `("opus","high")`; an agent with no rows → None; agent model None with a row set elsewhere → `("", "")` for review).
  - `test_run_start_carries_the_stages_model` (via `_hello_v2(agent, capabilities=(..., "stagemodel/1"))` and `_make_workflow(db, run_id, role="plan")`: `start["model_choice"] == {"model": "fable", "effort": ""}`).
  - `test_no_rows_no_model_choice` (no rows: `"model_choice"` is `None` in the start).
  - `test_an_older_runner_leaves_only_overridden_stages_queued` (rows set for plan; runner without `stagemodel/1`: a plan run stays queued and the agent's problems include `STAGE_MODEL_PROBLEM`; an implement run (row unset) is sent and carries no `model_choice`).
- [ ] **Step 2: Run** `uv run pytest tests/agents/test_stage_models.py tests/runner/test_protocol_v2.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `stage_models.py` as in Interfaces.
  - `_send_start`: for a workflow run and a `conn` with the capability, set `v2["model_choice"] = run_model(agent, role)` (load the agent with `db.get(Agent, agent_id)`).
  - `_claim_next`: add `true() if stagemodel else ~AgentRun.workflow_role.in_([r.value for r in overriding_roles(agent)])` to `runnable`, and `true()` when that set is empty.
  - `agent_problems`: gains a `stages: bool = False` parameter that adds `STAGE_MODEL_PROBLEM` without the capability; the caller passes `bool(overriding_roles(a))`.
- [ ] **Step 4: Run** `uv run pytest tests/agents tests/runner tests/agent_runs -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(agents): each workflow run starts on its stage's model and effort`.

### Task 5: Frontend — the Model by stage table

**Files:**
- Create: `frontend/src/components/agents/StageModelsField.tsx`
- Modify: `frontend/src/lib/agents.ts`, `frontend/src/components/agents/ModelField.tsx` (use the shared helpers), `frontend/src/components/agents/AgentsTab.tsx` (~58-80), `frontend/src/lib/api-types.ts` (`npm run gen:api`)
- Test: `frontend/src/components/agents/__tests__/StageModelsField.test.tsx`, `frontend/src/components/agents/__tests__/AgentsTab.test.tsx`

**Interfaces:**
- Consumes: Task 3's API (`stage_models` on the agent; PATCH `{stage_models}` replaces it).
- Produces in `lib/agents.ts`: `type StageKey = "design" | "plan" | "build" | "review" | "finish"`; `type StageModels = Partial<Record<StageKey, { model?: string | null; effort?: string | null }>>`; `STAGE_ROWS: { key: StageKey; label: string; note?: string }[]` = Design; Plan; Build ("steps and their fixes"); Review ("step, final and pull request reviews"); Finish. `findModel(known: ModelOption[], m: string | null): ModelOption | undefined` and `effortLevels(known: ModelOption[], m: string | null): { value: string; name: string }[]` (moved out of `ModelField`, same behaviour); `staleStageEfforts(rows: StageModels, known: ModelOption[], agentModel: string | null): StageKey[]` (rows with no model whose effort `agentModel` doesn't offer).
- `StageModelsField({ agentModel, agentEffort, knownModels, value, onSave }: { agentModel: string | null; agentEffort: string | null; knownModels: ModelOption[]; value: StageModels; onSave: (rows: StageModels) => Promise<void> | void })`.

- [ ] **Step 1: Write the failing tests** (`StageModelsField.test.tsx`):
  - "lists the five stages, each As above by default": five rows; each Model select shows `As above (Opus 5.5)` and each Effort select `As above (High)`.
  - "a row with its own model offers that model's efforts, and Model default": picking `Fable 5.2` on Design calls `onSave({design: {model: "fable"}})`; that row's Effort options are Fable's levels, first `Model default`.
  - "marks rows that differ": the Design row's selects have `border-violet`; Plan's don't.
  - "picking a model without the row's effort drops the effort, with a note": with `design: {model: "fable", effort: "max"}`, picking a model without Max saves `{design: {model: …}}` and shows `<Model name> has no Max effort, so Design's effort went back to Model default.`
  - In `AgentsTab.test.tsx`, "resets an effort-only row the new model lacks": with `plan: {effort: "max"}`, changing the agent's model to one without Max PATCHes `{model: …, stage_models: {}}` in one request and shows `<Model name> has no Max effort, so Plan's effort went back to As above.`
- [ ] **Step 2: Run** `npx vitest run src/components/agents` (PowerShell) — Expected: FAIL.
- [ ] **Step 3: Implement** the helpers, `StageModelsField` (the mockup A table: under the agent's Settings, a "Model by stage" heading, one row per stage with Model and Effort `Select`s, `border-violet` on rows that set anything; on a phone the rows stack), `ModelField` using the helpers, and `AgentsTab` rendering the table and adding the stale-row reset to its model PATCH. Run `npm run gen:api` with the backend from Task 3 running, as README says.
- [ ] **Step 4: Run** `npx vitest run src/components/agents`, `npx tsc --noEmit`, `npx eslint` on the changed files — Expected: PASS, clean.
- [ ] **Step 5: Commit** `feat(agents): a Model by stage table on the agent's settings`.

### Task 6: Whole-branch checks

**Files:** none new (fix only what the checks find, each fix test-first).

- [ ] **Step 1:** `cd backend && uv run pytest -q` (one run at a time) — Expected: all pass.
- [ ] **Step 2:** `cd runner && go test ./...` — Expected: all pass.
- [ ] **Step 3:** `cd frontend && npm test` (PowerShell) — Expected: all pass.
- [ ] **Step 4:** Browser tests on a freshly built stack, exactly as AGENTS.md's block (with `BUILDX_BAKE_ENTITLEMENTS_FS=0`, the dev Caddy stopped and started again) — Expected: all pass.
- [ ] **Step 5:** Commit any fixes; the branch is ready for the finishing menu. The runner change needs a runner release when the owner says "release" (not part of this plan).
