# MegooColab

Open-source, self-hosted project management for humans and coding agents. See [docs/brd.md](docs/brd.md).

## Install (self-hosted)

Requirements: a server with Docker and the Docker Compose plugin.

```bash
git clone https://github.com/mmhy2003/MegooColab.git megoocolab && cd megoocolab/deploy
cp .env.example .env     # set SECRET_KEY (openssl rand -hex 32), POSTGRES_PASSWORD, SITE_ADDRESS, PUBLIC_URL
docker compose up -d --build
```

Open `PUBLIC_URL` and create the organization and its admin. The full guide, [docs/install.md](docs/install.md),
covers every `.env` variable, HTTPS, email, AI models, git connections and webhooks, notifications, a
developer's first agent, upgrades, backups and troubleshooting.

MegooColab is licensed under the [Apache License 2.0](LICENSE); see [NOTICE](NOTICE) for third-party content.

## Runner and MCP

**Runner.** Coding agents run on your own machine through `megoocolab-runner`, which
connects to the server over a WebSocket and only reports metadata (never file contents).
Install, login, service mode and the permission policies are described in
[runner/README.md](runner/README.md).

**MCP.** The server exposes an MCP endpoint (streamable HTTP, stateless) at `/api/mcp`.
Create a personal access token with the `mcp` scope and send it as
`Authorization: Bearer mgc_...`; a missing or invalid token gets HTTP 401.

## Development quick-start

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22+, Go (for the runner) and GNU Make
(on Windows: `winget install ezwinports.make`; the targets work from PowerShell, cmd or Git Bash).

```bash
make dev-build    # install the backend and frontend packages, build the runner into runner/bin
make dev          # start the containers below, migrate, then run the API, worker and frontend; Ctrl+C stops them
make dev-stop     # stop the dev containers (their data stays)
```

`make` alone lists every target. The production stack has its own: `make build` (images and the runner for
all six platforms), `make up`, `make stop`, `make logs` and `make runner`; they read `deploy/.env`. What
`make dev` does, step by step:

```bash
# 1. Database (PostgreSQL 17 + pgvector on localhost:5433; also creates megoo_test),
#    Meilisearch on localhost:7700 (key megoo-dev-master-key; the tests use it too),
#    Valkey on localhost:6379 (password megoo-dev-valkey; rate-limit counters, the tests use it too)
#    and Caddy on http://localhost:8080 (/api -> :8000, everything else -> :3000)
docker compose -f deploy/docker-compose.dev.yml up -d

# 2. Backend
cd backend
uv sync
uv run pytest                      # test suite (uses the megoo_test database)
export SECRET_KEY=megoo-dev-secret-key-not-for-production MEILI_MASTER_KEY=megoo-dev-master-key   # SECRET_KEY needs 16+ characters
uv run fastapi dev app/main.py     # API on http://localhost:8000/api/docs
uv run python -m app.worker        # background jobs (search indexing); needs the API's migrations

# 3. Frontend
cd frontend
npm install
npm test                           # unit tests (Vitest)
npm run gen:api                    # regenerate src/lib/api-types.ts after API changes
npm run dev                        # then open http://localhost:8080
```

### End-to-end test

Runs against a fresh production-style stack on http://localhost:8080:

```bash
cp deploy/.env.example .superpowers/e2e.env   # set SECRET_KEY, MEILI_MASTER_KEY, HTTP_PORT=8080, PUBLIC_URL=http://localhost:8080, AI_FAKE=true, MEMORY_EXTRACT_DELAY_SECONDS=2
docker compose -p megoo-e2e -f deploy/docker-compose.yml --env-file .superpowers/e2e.env up -d --build --wait
cd frontend && npx playwright install chromium && npx playwright test
docker compose -p megoo-e2e -f deploy/docker-compose.yml --env-file .superpowers/e2e.env down -v
```

### Agents end-to-end test

`frontend/e2e/agents.spec.ts` drives the whole path (UI, server, runner, agent) against the same stack as above. It needs the Go toolchain and `git` on the PATH. The test builds the runner and the fake agent itself into a temp directory (`go build -o <tmp>/megoocolab-runner ./runner`, `go build -o <tmp>/fakeagent ./runner/internal/fakeagent`), runs the runner on the host with an isolated config and cache directory (HOME, USERPROFILE, APPDATA, LOCALAPPDATA, XDG_CONFIG_HOME and XDG_CACHE_HOME all point at a temp dir), and points `MEGOO_ADAPTER_CLAUDE_CODE` at the fake agent. It covers the token, the agent and its binding, online and offline, a workflow run queued while the runner is offline that starts once when it connects (a read-only brainstorm whose write is denied), and MCP `create_task`. It needs a fresh stack: it creates the "Agents Team" team and the AGT project, which already exist on a stack it has run against, so bring the stack down with `down -v` before each run. When it ends, pass or fail, it removes its temp directory (binaries, repository, worktree and the runner config with the token). To run it:

```bash
cd frontend && npx playwright test e2e/agents.spec.ts
# optional: E2E_SCREENSHOT_DIR=<dir> saves light and dark screenshots of the agent pages
#           E2E_RUNNER_LOG=1 prints the runner output at the end
```

### Workflow end-to-end test

`frontend/e2e/workflow.spec.ts` takes a task from To Do to Done through the whole workflow (Brainstorm, Design, Plan, Build, Review, Done) with the fake agent, on the same stack and with the same requirements and set-up as the agents test. It creates the "Workflow Team" team and the WFL project, so it too needs a fresh stack; it can run alone or after the other specs (`npx playwright test` runs all three on one stack, each with its own project key).

The fake agent plays every role from one scenario (`FAKEAGENT_SCENARIO`): its steps are grouped by `if_prompt_contains` on text that only that role's prompt holds (the methodology heading, `## Step n of 2`, a resume text), and `mcp_call` steps call MegooColab's MCP tools with the run's own token. The runner also gets `FAKEAGENT_SESSIONS_DIR` (sessions survive across runs, so answers and fixes resume them), `FAKEAGENT_RESUME=1`, and `FAKEAGENT_REPORT_DIR`, where each agent process (one per run) writes its own report; the test reads them to check session resumes and that `.megoocolab/plan.md` was in the worktree during Build.

Along the way it answers a question through the sandboxed mockup, approves the design, rejects and then approves the plan, follows the thread's document version links, sees a step review ask for changes and the fix pass, stops and restarts the runner during step 2 (step 2 is retried once, nothing before it re-runs), and checks the pull request link and that the developer's checkout is untouched. Last, a second task's mockup tries to call `/api/auth/me`, read `document.cookie`, navigate the top window and post an undeclared choice; the test checks each is blocked and that no answer is recorded. To run it:

```bash
cd frontend && npx playwright test e2e/workflow.spec.ts
# optional: E2E_RUNNER_LOG=1 prints the runner output at the end
```

### Knowledge Base end-to-end test

`frontend/e2e/kb.spec.ts` covers the Knowledge Base on the same stack. It needs `AI_FAKE=true` in the env file: the backend and the worker then use local, deterministic embeddings instead of calling a provider (never set it in production). It configures an embeddings provider and tests it, creates a folder and a document, edits it from a stale tab (the save is refused and the draft kept), compares revisions, links a document to a task and to another document, waits for the worker to embed so that a word only semantic search can match is found, checks that a member of another team sees none of the team or project documents, uses the MCP tools with a personal token, and files an approved connect-only design. It creates the "KB Team" and "Outside Team" teams and the KBX project, so it needs a fresh stack too. To run it:

```bash
cd frontend && npx playwright test e2e/kb.spec.ts
```

### Memory end-to-end test

`frontend/e2e/memory.spec.ts` covers the collective memory on the same stack. Besides `AI_FAKE=true` it needs `MEMORY_EXTRACT_DELAY_SECONDS=2` in the env file (sources are normally read 60 seconds after their last change). It sets every AI job to one provider, waits for the worker to learn a conclusion from a comment, deletes it and checks that editing the comment does not bring it back, lets the memory dream (an induced pattern with its reasoning chain and a summary card), asks the memory, checks that a member of another team sees nothing from the project, and uses the `search_memory` and `ask_memory` MCP tools. It creates the "Memory Team" and "Memory Outsiders" teams and the MEM project, so it needs a fresh stack. To run it:

```bash
cd frontend && npx playwright test e2e/memory.spec.ts
```

### Questions end-to-end test

`frontend/e2e/questions.spec.ts` covers agent-to-agent questions on the same stack, with the same requirements as the workflow test (the Go toolchain and `git` on the PATH; it builds the runner and the fake agent into a temp directory). Task QAA-1 asks project QBB a question while no runner is online, so it waits ("Waiting on QBB"). The runner then starts, the fake agent answers from a temp QBB repository with a fake AWS key in the text (scrubbed to `[redacted]`), and the owner approves the draft with an edit. The answer is filed in QBB's Knowledge Base under `Q&A`, shows in QAA-1's thread, and is suggested when the same question is asked again and by the `find_answer` MCP tool. Someone in neither project gets 404, and with the runner stopped a second question is answered by a person from the Incoming tab. It creates the "Questions Team" team, a user and the QAA and QBB projects, so it needs a fresh stack. To run it:

```bash
cd frontend && npx playwright test e2e/questions.spec.ts
# optional: E2E_RUNNER_LOG=1 prints the runner output at the end
```

### Git and notifications end-to-end tests

`frontend/e2e/git.spec.ts` covers git integration on the same stack, with the same requirements as the workflow test (the Go toolchain and `git` on the PATH). It starts a fake GitHub Enterprise API on the host (`frontend/e2e/helpers/fakeGit.ts`, on a free port), which the stack reaches as `http://host.docker.internal:<port>` (the compose file maps that name for the backend and worker). An admin adds the connection in Admin → Git with a token and a webhook secret, and **Test** shows the fake login. Project GIT requires a human code review, and its repository is linked to the connection. The fake agent runs GIT-1 to Finish, which reports pull request #1: the task shows "PR open · checks pending" and waits. The fake host then marks it merged, and a signed webhook makes MegooColab look: the task finishes by itself. A forged or unsigned delivery gets 401. GIT-3's pull request #2 is closed without a merge: the workflow escalates `pr_closed`, and **Accept** finishes it.

`frontend/e2e/notifications.spec.ts` covers notifications on the same stack (it also builds the runner and the fake agent). The admin assigns NOT-1 to an invited member, whose bell shows 1, and the notification opens the task. A mention made with the comment picker reaches her; an outsider mentioned by hand gets nothing. The admin's agent submits NOT-2's design, and the owner is told it awaits approval. Turning off in-app assignments silences the next one.

Both create their own users, teams and projects (GIT and NOT), so they need a fresh stack. To run them:

```bash
cd frontend && npx playwright test e2e/git.spec.ts e2e/notifications.spec.ts
# optional: E2E_RUNNER_LOG=1 prints the runner output at the end
```

### Live mockups end-to-end test

`frontend/e2e/mockups.spec.ts` covers live mockups and the agent's records on the same stack (it also builds the runner and the fake agent). While the fake agent brainstorms MCK-1, it shows two mockup versions: the open task shows v1, then v2 replaces it with no reload. **Approve this version** on v2, the version the design was submitted with, approves the design. In Build, the implementer records a decision and a test run: the task's Decisions section shows the decision, and the plan step shows "✓ 3 passed — npm test". It creates the "Mockup Team" team and the MCK project, so it needs a fresh stack. To run it:

```bash
cd frontend && npx playwright test e2e/mockups.spec.ts
```

### Global search end-to-end test

`frontend/e2e/search.spec.ts` covers global search on the same stack. The env file needs `MEILI_MASTER_KEY` (any long random string: `openssl rand -hex 32`); the stack's `meilisearch` service holds the index. Bea, a member of project SRA but not SRB, presses Ctrl+K and types "retyr": SRA-1 "Retry failed card payments" appears within seconds of its creation, and SRB-1 never does. Enter opens the task. "See all results" opens the results page, where ticking Tasks and To do keeps SRA-1. After the admin renames SRA-1, Bea's search finds the new title. It creates the "Search Team" and "Search Private" teams, a user and the SRA and SRB projects, so it needs a fresh stack. To run it:

```bash
cd frontend && npx playwright test e2e/search.spec.ts
```

### Popups end-to-end test

`frontend/e2e/popups.spec.ts` checks clicks outside popups on the same stack. The user menu and the notification panel close on a click outside them (the panel on Escape too), and so does search (Ctrl+K). The "New team" dialog stays open with what was typed, and so does the task drawer; Escape closes both. The page behind each popup is blurred. It creates the "Popup Team" team and the POP project, so it needs a fresh stack. To run it:

```bash
cd frontend && npx playwright test e2e/popups.spec.ts
# optional: E2E_SCREENSHOT_DIR=<dir> saves a screenshot of each popup
```

### Layout end-to-end test

`frontend/e2e/layout.spec.ts` checks that the sidebar and the header bar stay in view while a long page scrolls (Admin → Settings in a 500-pixel-tall window), and that scrollbars stay hidden until the pointer is over the scrolling area, then fade in as a thin cyan bar, and that checkboxes are on/off switches that light up cyan when checked. It creates nothing, so it runs on any stack:

```bash
cd frontend && npx playwright test e2e/layout.spec.ts
```
