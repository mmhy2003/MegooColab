# MegooColab

Open-source, self-hosted project management for humans and coding agents. See [docs/brd.md](docs/brd.md).

## Install (self-hosted)

Requirements: a Linux server (or any Docker host) with Docker and Docker Compose.

```bash
git clone <this repo> megoocolab && cd megoocolab/deploy
cp .env.example .env
# edit .env:
#   SECRET_KEY        -> output of: openssl rand -hex 32
#   POSTGRES_PASSWORD -> any strong password
#   SITE_ADDRESS      -> your domain (e.g. megoo.example.com) for automatic HTTPS,
#                        or :80 for plain HTTP (trial / behind another proxy)
#   PUBLIC_URL        -> the URL people open, e.g. https://megoo.example.com
#   COOKIE_SECURE     -> true when served over HTTPS
docker compose up -d --build
```

Open `PUBLIC_URL`. The first visit asks you to create the organization and its admin account.
Database migrations run automatically when the backend starts.

Optional: **Admin → Settings** to configure email (SMTP) for invitations and password resets.
Without email, admins copy invite and reset links from the Users page.

**Upgrade:** `git pull && docker compose up -d --build` (migrations run on start).
**Backups:** the `pgdata` (database) and `uploads` (attachments) volumes hold all data.

## Runner and MCP

**Runner.** Coding agents run on your own machine through `megoocolab-runner`, which
connects to the server over a WebSocket and only reports metadata (never file contents).
Install, login, service mode and the permission policies are described in
[runner/README.md](runner/README.md).

**MCP.** The server exposes an MCP endpoint (streamable HTTP, stateless) at `/api/mcp`.
Create a personal access token with the `mcp` scope and send it as
`Authorization: Bearer mgc_...`; a missing or invalid token gets HTTP 401.

## Development quick-start

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node.js 22+.

```bash
# 1. Database (PostgreSQL 17 + pgvector on localhost:5433; also creates megoo_test)
#    and Caddy on http://localhost:8080 (/api -> :8000, everything else -> :3000)
docker compose -f deploy/docker-compose.dev.yml up -d

# 2. Backend
cd backend
uv sync
uv run pytest                      # test suite (uses the megoo_test database)
SECRET_KEY=dev uv run fastapi dev app/main.py   # API on http://localhost:8000/api/docs
SECRET_KEY=dev uv run python -m app.worker      # background jobs (search indexing); needs the API's migrations

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
cp deploy/.env.example .superpowers/e2e.env   # set SECRET_KEY, HTTP_PORT=8080, PUBLIC_URL=http://localhost:8080, AI_FAKE=true, MEMORY_EXTRACT_DELAY_SECONDS=2
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
