# Installing MegooColab

This guide takes you from an empty server to a working MegooColab: the organization, email, AI models, git
connections and notifications, then a developer's first agent at work. Each command is meant to be run as
written, from the directory the step names.

## 1. Requirements

- A Linux server (or any machine with Docker) with **Docker Engine 24+** and the **Docker Compose plugin**
  (`docker compose version` prints v2.20 or newer).
- 2 CPU cores, 4 GB of RAM and 20 GB of disk are enough for dozens of users and agents.
- For HTTPS: a domain name whose DNS points at the server, and ports 80 and 443 open to the internet.
- `git` and `openssl` on the server.

Developers who connect coding agents need, on their own computers: `git`, Node.js 20+ (with `npx`), and the
coding agent itself (Claude Code or Codex) signed in with their own subscription or key. See section 11.

## 2. Get the code

```bash
git clone https://github.com/mmhy2003/MegooColab.git megoocolab
cd megoocolab/deploy
```

Everything below runs from this `deploy` directory unless it says otherwise.

## 3. `.env`

```bash
cp .env.example .env
```

Then edit `.env`. Every variable:

| Variable | What it is | Example |
|---|---|---|
| `SITE_ADDRESS` | What Caddy serves. A domain gets automatic HTTPS from Let's Encrypt; `:80` serves plain HTTP (a trial, or behind another proxy that terminates TLS). | `megoo.example.com` |
| `HTTP_PORT` | The host port for HTTP. | `80` |
| `HTTPS_PORT` | The host port for HTTPS. | `443` |
| `PUBLIC_URL` | The address people open, with no trailing slash. Invitation, password-reset and notification emails link to it. | `https://megoo.example.com` |
| `COOKIE_SECURE` | `true` when served over HTTPS, so session cookies are only sent over HTTPS. | `true` |
| `SECRET_KEY` | Signs sessions and encrypts stored secrets (SMTP password, AI keys, git tokens). Generate it once with `openssl rand -hex 32`; the backend refuses to start with the example value. **Keep it: changing it makes the stored secrets unreadable.** | 64 hex characters |
| `POSTGRES_PASSWORD` | The database password, used only between the containers. | a long random string |
| `MEMORY_DREAM_HOUR_UTC` | The hour (0–23, UTC) the memory "dreams" each night, unless an admin sets another one under Admin → Settings. | `3` |
| `AI_FAKE` | Tests only: local fake embeddings and no AI provider calls. Never set it in production. | *(unset)* |
| `MEMORY_EXTRACT_DELAY_SECONDS` | Tests only: how long after a change the memory reads a source (default 60). | *(unset)* |

A quick way to fill in the two secrets:

```bash
sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$(openssl rand -hex 32)/" .env
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env
```

## 4. Start

```bash
docker compose up -d --build
docker compose ps
```

The first build takes a few minutes. When `docker compose ps` shows the backend as `healthy`, MegooColab is up.
Database migrations run by themselves each time the backend starts.

The stack has six services: `db` (PostgreSQL 17 with pgvector), `backend` (the API), `worker` (background
jobs: search indexing, memory, pull-request checks, email), `frontend`, and `caddy` (the web server in front).

Check it answers:

```bash
curl -s http://localhost/api/setup/status
# {"needs_setup":true}
```

(Add your `HTTP_PORT`, e.g. `http://localhost:8090/...`, if you changed it.)

## 5. First run: the organization and admin

Open `PUBLIC_URL` in a browser. The first visit asks you to set up your organization and admin account: the
organization's name and the first admin's name, email and password. That admin can then invite everyone else from **Admin → Users**.
Without email (section 7) the invitation link is shown to the admin to copy and send.

Roles: **admin** (everything), **manager** (creates and manages projects of their teams), **member** (works on
tasks), **viewer** (reads only).

## 6. HTTPS and domains (Caddy)

With `SITE_ADDRESS` set to a domain, Caddy obtains and renews a Let's Encrypt certificate on its own. Point the
domain's DNS at the server, open ports 80 and 443, set `PUBLIC_URL=https://<domain>` and `COOKIE_SECURE=true`,
then apply the change:

```bash
docker compose up -d
```

Behind another reverse proxy or load balancer that handles TLS, keep `SITE_ADDRESS=:80`, set `HTTP_PORT` to a
free port, proxy to it (WebSockets must be passed through: the live board and the runners use them), and still
set `PUBLIC_URL` to the public `https://` address and `COOKIE_SECURE=true`.

Certificates live in the `caddy_data` volume; keep it to avoid asking Let's Encrypt for new ones.

## 7. Email (SMTP)

Under **Admin → Settings → Email (SMTP)** enter the host, port (587 with STARTTLS is the common choice), user,
password and from-address, save, and use **Send test**. MegooColab then emails invitations, password resets
and notifications. The password is stored encrypted and never shown again.

## 8. AI providers and models (Admin → AI)

The memory, its nightly dreaming and the Knowledge Base search call AI models with your organization's own
keys (through LiteLLM). Coding agents do not use these; they run on each developer's machine.

1. **Providers:** add one per account, for example kind `openai` with an API key, or `ollama` with an API base
   such as `http://host.docker.internal:11434`. Keys are stored encrypted.
2. **Models:** choose a provider and model for each job: **Embeddings** (search and memory), **Extraction**
   (learning from tasks, comments and documents), **Dreaming** (the nightly pass) and **Answering** (questions
   to the memory).
3. **Admin → Settings → Dreaming** turns the nightly pass off or sets its hour (UTC).

Until embeddings are set, the Knowledge Base still works with keyword search.

## 9. Git connections and webhooks

MegooColab follows the pull requests its agents open: whether the checks pass, whether a reviewer approved,
and when a person merges. A merge finishes the task. It needs a **read-only** token per git host; it never
pushes or merges.

### Create the token

| Host | Token | Scopes |
|---|---|---|
| GitHub / GitHub Enterprise | A fine-grained personal access token (or a GitHub App's) for the repositories | **Pull requests: read**, **Commit statuses: read**, **Checks: read** (Metadata: read is added for you) |
| GitLab | A project, group or personal access token | `read_api` |
| Gitea / Forgejo | An access token | `read:repository` |

### Add the connection (Admin → Git)

**Add connection**: a name, the kind, the base URL (`https://github.com` for github.com, your server's address
for GitHub Enterprise, GitLab or Gitea, e.g. `https://git.example.com`), the token, and optionally a webhook
secret (`openssl rand -hex 20`). **Test** shows the account the token belongs to. The token and secret are
stored encrypted and never shown again; leave them empty when editing to keep them.

Then, in each project, **Settings → Repositories**: pick the connection next to each repository. A repository
without a connection is not tracked: its pull request shows "PR (not tracked)" and a person uses **Mark merged**
once it is merged.

### Webhooks (optional, recommended)

Without webhooks, MegooColab checks open pull requests every 2 minutes. With them, changes show within seconds.
The connection's row under Admin → Git shows its webhook URL:

```
https://<your host>/api/git/webhooks/<connection id>
```

- **GitHub:** repository (or organization) **Settings → Webhooks → Add webhook**. Payload URL: the URL above;
  content type `application/json`; secret: the connection's webhook secret; events: *Pull requests*,
  *Pull request reviews*, *Check runs*, *Check suites* and *Statuses*.
- **GitLab:** project or group **Settings → Webhooks**. URL: the URL above; secret token: the webhook secret;
  triggers: *Merge request events* and *Pipeline events*.
- **Gitea / Forgejo:** repository **Settings → Webhooks → Add webhook → Gitea** (or Forgejo). Target URL: the
  URL above; content type `application/json`; secret: the webhook secret; events: *Pull request* events and
  *Status*.

The git host must be able to reach `PUBLIC_URL`. A delivery is only a hint: MegooColab verifies its signature,
then reads the pull request's state from the host's API with the token. A self-hosted git server on the same
machine as MegooColab is reachable from the containers as `host.docker.internal`.

## 10. Notifications

The bell in the header shows what needs you: a task waiting on your answer, approval or review, a task assigned
to you or your agent, a mention (`@` in a comment), your agent going offline mid-task, and agent-to-agent
questions that need a person. Each person chooses, per kind, in-app and email under **avatar → Notifications**
(`/settings/notifications`). Email needs SMTP (section 7); its links use `PUBLIC_URL`.

## 11. Developers: the first agent at work

What a developer does after receiving an invitation, in about 15 minutes:

1. **Accept the invitation** (the email link, or the link an admin sent) and set a password.
2. **Create a runner token:** avatar → **Access tokens** → create a token with the **Runner** scope. Copy it; it is shown once.
3. **Install the runner** on the computer where the code and the coding agent live:
   - Linux and macOS:
     ```sh
     curl -fsSL https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/install.sh | sh
     ```
   - Windows (Scoop):
     ```powershell
     scoop install https://raw.githubusercontent.com/mmhy2003/MegooColab/main/runner/scoop/megoocolab-runner.json
     ```
4. **Sign in and check:**
   ```sh
   megoocolab-runner login --url https://megoo.example.com --token mgc_...
   megoocolab-runner doctor
   ```
   `doctor` checks the server, Node.js, git and the agent adapters.
5. **Register the agent:** avatar → **My agents** → Add agent (Claude Code or Codex), then bind it to the project
   with the path of your local clone of the project's repository.
6. **Start the runner:** `megoocolab-runner run` (or `megoocolab-runner service install` and
   `megoocolab-runner service start` to keep it running in the background). The agent shows **Online**.
7. **Give it a task:** on the project board, assign a task to the agent and drag it to **In Progress**. The
   agent starts brainstorming in its own git worktree; the board, the task's thread and the bell show what it
   does and when it needs you.

The runner's own guide, including the permission policies and service mode on each OS, is
[runner/README.md](../runner/README.md). Agents can also use MegooColab's tools over MCP: create a token with
the **MCP** scope and point the agent at `https://<your host>/api/mcp` with the header
`Authorization: Bearer mgc_...`.

## 12. Upgrades

```bash
git pull
docker compose up -d --build
```

Migrations run when the backend starts. Take a backup first (section 13).

## 13. Backups and restore

All data lives in the database and the uploaded attachments. From the `deploy` directory:

**Back up:**

```bash
docker compose exec -T db pg_dump -U megoo -Fc megoo > megoo.dump
docker compose exec -T backend tar czf - -C /data/uploads . > uploads.tgz
```

Keep both files, and `.env` (above all `SECRET_KEY`: without it, the stored SMTP password, AI keys and git
tokens cannot be decrypted), somewhere off the server.

**Restore** (onto a running stack, for example a fresh install with the same `.env`):

```bash
docker compose stop backend worker
docker compose exec -T db pg_restore -U megoo -d megoo --clean --if-exists --no-owner < megoo.dump
docker compose start backend worker
docker compose exec -T backend tar xzf - -C /data/uploads < uploads.tgz
```

## 14. Troubleshooting

- **See what a service says:** `docker compose logs -f backend` (or `worker`, `caddy`, `db`).
- **The backend keeps restarting:** `SECRET_KEY` is still the example value, or the database password in `.env`
  changed after the first start (the database keeps the first one). The log says which.
- **Signing in seems to work but you are sent back to the login page:** the page is served over plain HTTP while
  `COOKIE_SECURE=true`, so the browser drops the session cookie. Serve it over HTTPS or set `COOKIE_SECURE=false`.
- **No HTTPS certificate:** the domain's DNS does not point at the server yet, or ports 80/443 are blocked;
  `docker compose logs caddy` shows Let's Encrypt's answer.
- **Emails do not arrive:** use **Send test** under Admin → Settings; the error shown comes from the mail server.
- **The agent stays Offline:** run `megoocolab-runner doctor` on the developer's computer; check the token has the
  Runner scope and that WebSockets reach `/api/runner/ws` through any proxy.
- **A pull request is not followed:** the repository has no git connection (project Settings → Repositories),
  **Test** fails under Admin → Git, or the pull request URL is on another host than the connection's base URL.
- **Webhook deliveries fail with 401:** the secret in the git host differs from the connection's; with 404, the
  connection has no webhook secret or the id in the URL is wrong.
